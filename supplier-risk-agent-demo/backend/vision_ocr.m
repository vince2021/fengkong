#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#import <PDFKit/PDFKit.h>
#import <Vision/Vision.h>

static NSArray<NSDictionary *> *RecognizeImage(CGImageRef image, NSInteger page, NSError **error) {
    VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] init];
    request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
    request.recognitionLanguages = @[@"zh-Hans", @"en-US"];
    request.usesLanguageCorrection = YES;
    VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:image options:@{}];
    if (![handler performRequests:@[request] error:error]) return @[];
    NSMutableArray<NSDictionary *> *lines = [NSMutableArray array];
    for (VNRecognizedTextObservation *observation in request.results ?: @[]) {
        VNRecognizedText *candidate = [[observation topCandidates:1] firstObject];
        if (!candidate || candidate.string.length == 0) continue;
        [lines addObject:@{@"text": candidate.string, @"confidence": @(candidate.confidence), @"page": @(page)}];
    }
    return lines;
}

static CGImageRef CreateImageFromPDFPage(PDFPage *page) {
    NSRect bounds = [page boundsForBox:kPDFDisplayBoxMediaBox];
    CGFloat longestEdge = MAX(bounds.size.width, bounds.size.height);
    CGFloat scale = longestEdge > 0 ? MIN(2.0, 2500.0 / longestEdge) : 1.0;
    scale = MAX(scale, 0.1);
    size_t width = MAX((size_t)(bounds.size.width * scale), 1);
    size_t height = MAX((size_t)(bounds.size.height * scale), 1);
    CGColorSpaceRef colorSpace = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(NULL, width, height, 8, 0, colorSpace, kCGImageAlphaPremultipliedLast);
    CGColorSpaceRelease(colorSpace);
    if (!context) return NULL;
    CGContextSetRGBFillColor(context, 1, 1, 1, 1);
    CGContextFillRect(context, CGRectMake(0, 0, width, height));
    CGContextScaleCTM(context, scale, scale);
    [page drawWithBox:kPDFDisplayBoxMediaBox toContext:context];
    CGImageRef image = CGBitmapContextCreateImage(context);
    CGContextRelease(context);
    return image;
}

static CGImageRef CreateBoundedImage(CGImageRef source) {
    size_t sourceWidth = CGImageGetWidth(source);
    size_t sourceHeight = CGImageGetHeight(source);
    size_t longestEdge = MAX(sourceWidth, sourceHeight);
    if (longestEdge <= 3000) return CGImageCreateCopy(source);
    CGFloat scale = 3000.0 / (CGFloat)longestEdge;
    size_t width = MAX((size_t)(sourceWidth * scale), 1);
    size_t height = MAX((size_t)(sourceHeight * scale), 1);
    CGColorSpaceRef colorSpace = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(NULL, width, height, 8, 0, colorSpace, kCGImageAlphaPremultipliedLast);
    CGColorSpaceRelease(colorSpace);
    if (!context) return NULL;
    CGContextSetInterpolationQuality(context, kCGInterpolationHigh);
    CGContextDrawImage(context, CGRectMake(0, 0, width, height), source);
    CGImageRef result = CGBitmapContextCreateImage(context);
    CGContextRelease(context);
    return result;
}

static void PrintResult(NSString *status, NSInteger pages, NSArray *lines, NSString *warning) {
    NSMutableDictionary *payload = [@{
        @"status": status,
        @"provider": @"macos_vision",
        @"pagesProcessed": @(pages),
        @"lines": lines ?: @[]
    } mutableCopy];
    if (warning) payload[@"warning"] = warning;
    NSData *data = [NSJSONSerialization dataWithJSONObject:payload options:0 error:nil];
    fwrite(data.bytes, 1, data.length, stdout);
    fputc('\n', stdout);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc < 2) {
            PrintResult(@"error", 0, @[], @"缺少输入文件");
            return 2;
        }
        NSString *path = [NSString stringWithUTF8String:argv[1]];
        NSInteger maxPages = argc >= 3 ? MAX(atoi(argv[2]), 1) : 5;
        NSMutableArray<NSDictionary *> *allLines = [NSMutableArray array];
        NSInteger pagesProcessed = 0;
        NSError *error = nil;
        if ([[path.pathExtension lowercaseString] isEqualToString:@"pdf"]) {
            PDFDocument *document = [[PDFDocument alloc] initWithURL:[NSURL fileURLWithPath:path]];
            if (!document) {
                PrintResult(@"error", 0, @[], @"PDF 无法打开");
                return 1;
            }
            pagesProcessed = MIN(document.pageCount, maxPages);
            for (NSInteger index = 0; index < pagesProcessed; index++) {
                PDFPage *page = [document pageAtIndex:index];
                CGImageRef image = page ? CreateImageFromPDFPage(page) : NULL;
                if (!image) continue;
                [allLines addObjectsFromArray:RecognizeImage(image, index + 1, &error)];
                CGImageRelease(image);
                if (error) break;
            }
        } else {
            NSImage *source = [[NSImage alloc] initWithContentsOfFile:path];
            CGImageRef original = source ? [source CGImageForProposedRect:NULL context:nil hints:nil] : NULL;
            CGImageRef image = original ? CreateBoundedImage(original) : NULL;
            if (!image) {
                PrintResult(@"error", 0, @[], @"图片无法打开");
                return 1;
            }
            pagesProcessed = 1;
            [allLines addObjectsFromArray:RecognizeImage(image, 1, &error)];
            CGImageRelease(image);
        }
        if (error) {
            PrintResult(@"error", pagesProcessed, @[], error.localizedDescription);
            return 1;
        }
        PrintResult(allLines.count ? @"success" : @"no_text", pagesProcessed, allLines, allLines.count ? nil : @"未识别到文本");
        return 0;
    }
}
