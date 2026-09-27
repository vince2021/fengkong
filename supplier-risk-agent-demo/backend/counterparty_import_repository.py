"""Two-phase, tenant-scoped counterparty JSON/CSV imports."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.counterparty_repository import CounterpartyRepository
from backend.counterparty_schemas import CounterpartyCreate
from backend.db_models import CounterpartyImportBatchRecord, CounterpartyRecord
from backend.repository import AuditRepository, content_hash

if TYPE_CHECKING:
    from backend.security import Principal


MAX_IMPORT_ROWS = 500
MAX_IMPORT_BYTES = 2 * 1024 * 1024
CANONICAL_FIELDS = {
    "counterparty_id", "credit_code", "name", "counterparty_type", "industry", "cooperation_status",
    "is_key_counterparty", "requested_limit", "current_limit", "current_payment_term_days",
    "current_rating", "current_segment", "external", "internal", "financial", "extensions",
}
NUMERIC_FIELDS = {"requested_limit", "current_limit"}
INTEGER_FIELDS = {"current_payment_term_days"}
BOOLEAN_FIELDS = {"is_key_counterparty"}


class CounterpartyImportError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CounterpartyImportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def precheck(self, payload: dict, principal: "Principal") -> dict:
        content = payload["content"]
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_IMPORT_BYTES:
            raise CounterpartyImportError("COUNTERPARTY_IMPORT_TOO_LARGE", "导入文件不能超过 2MB", 422)
        source_hash = hashlib.sha256(content_bytes).hexdigest()
        request_hash = content_hash({
            "file_name": payload["file_name"], "file_format": payload["file_format"],
            "source_hash": source_hash, "duplicate_strategy": payload["duplicate_strategy"],
            "field_mapping": payload["field_mapping"],
        })
        existing = self.session.scalars(
            select(CounterpartyImportBatchRecord).where(
                CounterpartyImportBatchRecord.tenant_id == principal.tenant_id,
                CounterpartyImportBatchRecord.import_key == payload["import_key"],
            )
        ).first()
        if existing:
            if existing.request_hash != request_hash:
                raise CounterpartyImportError(
                    "COUNTERPARTY_IMPORT_KEY_CONFLICT", "导入批次编号已存在，但文件内容或配置不同", 409
                )
            return self._view(existing, idempotent=True)

        raw_rows, parse_receipts = self._parse(content, payload["file_format"])
        if len(raw_rows) > MAX_IMPORT_ROWS:
            raise CounterpartyImportError(
                "COUNTERPARTY_IMPORT_TOO_MANY_ROWS", f"单批最多导入 {MAX_IMPORT_ROWS} 条客商", 422
            )
        normalized_rows, receipts = self._normalize_rows(
            raw_rows, payload["file_format"], payload["field_mapping"], parse_receipts
        )
        self._classify_actions(principal.tenant_id, normalized_rows, receipts, payload["duplicate_strategy"])
        invalid_count = sum(bool(item["errors"]) for item in receipts)
        valid_count = len(receipts) - invalid_count
        create_count = sum(item.get("action") == "create" and not item["errors"] for item in receipts)
        update_count = sum(item.get("action") == "update" and not item["errors"] for item in receipts)
        skip_count = sum(item.get("action") == "skip" and not item["errors"] for item in receipts)
        status = "blocked" if invalid_count else "prechecked"
        frozen = {
            "tenant_id": principal.tenant_id,
            "import_key": payload["import_key"],
            "source_hash": source_hash,
            "duplicate_strategy": payload["duplicate_strategy"],
            "field_mapping": payload["field_mapping"],
            "normalized_rows": normalized_rows,
            "row_receipts": receipts,
            "counts": {
                "total": len(receipts), "valid": valid_count, "invalid": invalid_count,
                "create": create_count, "update": update_count, "skip": skip_count,
            },
        }
        record = CounterpartyImportBatchRecord(
            id=str(uuid4()), tenant_id=principal.tenant_id, import_key=payload["import_key"],
            file_name=payload["file_name"], file_format=payload["file_format"],
            duplicate_strategy=payload["duplicate_strategy"], field_mapping_json=deepcopy(payload["field_mapping"]),
            source_content=content, source_hash=source_hash, request_hash=request_hash,
            preview_hash=content_hash(frozen), normalized_rows_json=deepcopy(normalized_rows),
            row_receipts_json=deepcopy(receipts), status=status, total_count=len(receipts),
            valid_count=valid_count, invalid_count=invalid_count, create_count=create_count,
            update_count=update_count, skip_count=skip_count, committed_count=0,
            precheck_reason=payload["reason"], created_by=principal.subject, created_by_name=principal.name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append(
                "counterparty_import", f"{record.tenant_id}:{record.import_key}",
                "counterparty_import_prechecked", principal.subject,
                self._audit_payload(record, principal, payload["reason"]),
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            concurrent = self.session.scalars(
                select(CounterpartyImportBatchRecord).where(
                    CounterpartyImportBatchRecord.tenant_id == principal.tenant_id,
                    CounterpartyImportBatchRecord.import_key == payload["import_key"],
                )
            ).first()
            if concurrent and concurrent.request_hash == request_hash:
                return self._view(concurrent, idempotent=True)
            raise CounterpartyImportError(
                "COUNTERPARTY_IMPORT_CONCURRENT_CONFLICT", "客商导入预检发生并发冲突，请刷新后重试", 409
            ) from exc
        self.session.refresh(record)
        return self._view(record)

    def commit(self, batch_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._record(principal.tenant_id, batch_id)
        if record.preview_hash != payload["preview_hash"]:
            raise CounterpartyImportError("COUNTERPARTY_IMPORT_PREVIEW_MISMATCH", "预检证据哈希不一致，禁止提交", 409)
        if record.status == "committed":
            return self._view(record, idempotent=True)
        if record.status == "blocked" or record.invalid_count:
            raise CounterpartyImportError("COUNTERPARTY_IMPORT_BLOCKED", "预检存在行级错误，修复文件后使用新批次重新预检", 422)
        if record.row_version != payload["expected_row_version"]:
            raise CounterpartyImportError("COUNTERPARTY_IMPORT_VERSION_CONFLICT", "导入批次已更新，请刷新后重试", 409)
        if hashlib.sha256(record.source_content.encode("utf-8")).hexdigest() != record.source_hash:
            raise CounterpartyImportError("COUNTERPARTY_IMPORT_SOURCE_TAMPERED", "冻结的导入原文完整性校验失败", 409)
        if self._preview_hash(record) != record.preview_hash:
            raise CounterpartyImportError("COUNTERPARTY_IMPORT_PREVIEW_TAMPERED", "冻结的预检结果完整性校验失败", 409)

        operations: list[tuple[str, CounterpartyRecord, dict | None]] = []
        try:
            for frozen in record.normalized_rows_json or []:
                action = frozen["_import_action"]
                if action == "create":
                    if self._find_collision(record.tenant_id, frozen):
                        raise CounterpartyImportError(
                            "COUNTERPARTY_IMPORT_STALE", "预检后客商主数据已变化，请使用新批次重新预检", 409
                        )
                    counterparty = self._new_counterparty(record, frozen, principal)
                    self.session.add(counterparty)
                    operations.append(("counterparty_created", counterparty, None))
                    continue

                current = self._existing_by_id(record.tenant_id, frozen["counterparty_id"])
                if current is None or current.status != "active":
                    raise CounterpartyImportError(
                        "COUNTERPARTY_IMPORT_STALE", "预检后的客商已不存在或被归档，请重新预检", 409
                    )
                if current.row_version != frozen["_expected_row_version"] or current.profile_hash != frozen["_expected_profile_hash"]:
                    raise CounterpartyImportError(
                        "COUNTERPARTY_IMPORT_STALE", "预检后客商主数据已变化，请重新预检", 409
                    )
                if action == "skip":
                    continue
                collision = self._existing_by_code(record.tenant_id, frozen["credit_code"])
                if collision is not None and collision.id != current.id:
                    raise CounterpartyImportError(
                        "COUNTERPARTY_IMPORT_STALE", "预检后统一信用代码已被其他客商占用，请重新预检", 409
                    )
                before = CounterpartyRepository._snapshot(current)
                self._apply_values(current, frozen)
                current.source_type = "batch_import"
                current.updated_by = principal.subject
                current.profile_hash = CounterpartyRepository._profile_hash(current)
                operations.append(("counterparty_updated", current, before))

            record.status = "committed"
            record.committed_count = record.create_count + record.update_count
            record.commit_reason = payload["reason"]
            record.committed_by = principal.subject
            record.committed_by_name = principal.name
            record.committed_at = datetime.now(timezone.utc)
            self.session.flush()
            for event_type, counterparty, before in operations:
                self.audit.append(
                    "counterparty", f"{record.tenant_id}:{counterparty.counterparty_id}", event_type,
                    principal.subject,
                    {
                        "tenant_id": record.tenant_id, "counterparty_id": counterparty.counterparty_id,
                        "actor_name": principal.name, "reason": payload["reason"], "source": "counterparty_import",
                        "import_id": record.id, "import_key": record.import_key, "preview_hash": record.preview_hash,
                        "before": before, "after": CounterpartyRepository._snapshot(counterparty),
                    },
                )
            self.audit.append(
                "counterparty_import", f"{record.tenant_id}:{record.import_key}",
                "counterparty_import_committed", principal.subject,
                self._audit_payload(record, principal, payload["reason"]),
            )
            self.session.commit()
        except CounterpartyImportError:
            self.session.rollback()
            raise
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise CounterpartyImportError(
                "COUNTERPARTY_IMPORT_CONCURRENT_CONFLICT", "导入提交发生并发冲突，整批已回滚，请重新预检", 409
            ) from exc
        self.session.refresh(record)
        return self._view(record)

    def get(self, tenant_id: str, batch_id: str) -> dict:
        return self._view(self._record(tenant_id, batch_id))

    def correction_draft(self, tenant_id: str, batch_id: str) -> dict:
        record = self._record(tenant_id, batch_id)
        if record.status != "blocked":
            raise CounterpartyImportError(
                "COUNTERPARTY_IMPORT_NOT_BLOCKED", "仅预检阻断批次可以复制为修正草稿", 422
            )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return {
            "source_batch_id": record.id,
            "source_import_key": record.import_key,
            "source_hash": record.source_hash,
            "suggested_import_key": f"CP-CORRECT-{timestamp}-{record.id[:6].upper()}",
            "file_name": record.file_name,
            "file_format": record.file_format,
            "content": record.source_content,
            "duplicate_strategy": record.duplicate_strategy,
            "field_mapping": deepcopy(record.field_mapping_json or {}),
        }

    def receipt_csv(self, tenant_id: str, batch_id: str) -> tuple[str, bytes]:
        record = self._record(tenant_id, batch_id)
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([
            "行号", "客商编号", "统一社会信用代码", "处理动作", "错误代码", "错误字段",
            "错误信息", "警告代码", "警告信息",
        ])
        for receipt in record.row_receipts_json or []:
            errors = receipt.get("errors") or []
            warnings = receipt.get("warnings") or []
            writer.writerow([
                receipt.get("row_number", ""),
                receipt.get("counterparty_id") or "",
                receipt.get("credit_code") or "",
                receipt.get("action") or "",
                " | ".join(str(item.get("code") or "") for item in errors),
                " | ".join(str(item.get("field") or "") for item in errors),
                " | ".join(str(item.get("message") or "") for item in errors),
                " | ".join(str(item.get("code") or "") for item in warnings),
                " | ".join(str(item.get("message") or "") for item in warnings),
            ])
        return f"{record.import_key}-receipt.csv", ("\ufeff" + output.getvalue()).encode("utf-8")

    def list(self, tenant_id: str, *, status: str | None, limit: int, offset: int) -> dict:
        filters = [CounterpartyImportBatchRecord.tenant_id == tenant_id]
        if status:
            filters.append(CounterpartyImportBatchRecord.status == status)
        total = self.session.scalar(select(func.count(CounterpartyImportBatchRecord.id)).where(*filters)) or 0
        rows = self.session.scalars(
            select(CounterpartyImportBatchRecord).where(*filters)
            .order_by(CounterpartyImportBatchRecord.created_at.desc(), CounterpartyImportBatchRecord.id.desc())
            .offset(offset).limit(limit)
        ).all()
        return {"items": [self._view(row) for row in rows], "total": int(total), "limit": limit, "offset": offset}

    def _classify_actions(self, tenant_id: str, rows: list[dict], receipts: list[dict], strategy: str) -> None:
        ids = [row["counterparty_id"] for row in rows if row]
        codes = [row["credit_code"] for row in rows if row]
        duplicate_ids = {value for value, count in Counter(ids).items() if count > 1}
        duplicate_codes = {value for value, count in Counter(codes).items() if count > 1}
        existing = self.session.scalars(
            select(CounterpartyRecord).where(
                CounterpartyRecord.tenant_id == tenant_id,
                or_(CounterpartyRecord.counterparty_id.in_(ids), CounterpartyRecord.credit_code.in_(codes)),
            )
        ).all() if ids else []
        by_id = {row.counterparty_id: row for row in existing}
        by_code = {row.credit_code: row for row in existing}
        for row, receipt in zip(rows, receipts):
            if not row:
                receipt["action"] = "reject"
                continue
            if row["counterparty_id"] in duplicate_ids:
                self._row_error(receipt, "counterparty_id", "DUPLICATE_IN_FILE", "文件内客商编号重复")
            if row["credit_code"] in duplicate_codes:
                self._row_error(receipt, "credit_code", "DUPLICATE_IN_FILE", "文件内统一信用代码重复")
            if receipt["errors"]:
                receipt["action"] = "reject"
                continue
            id_match = by_id.get(row["counterparty_id"])
            code_match = by_code.get(row["credit_code"])
            if id_match is None and code_match is None:
                row["_import_action"] = receipt["action"] = "create"
                continue
            if id_match is None:
                self._row_error(receipt, "credit_code", "CREDIT_CODE_OCCUPIED", "统一信用代码已属于其他客商编号")
                receipt["action"] = "reject"
                continue
            if code_match is not None and code_match.id != id_match.id:
                self._row_error(receipt, "credit_code", "CREDIT_CODE_OCCUPIED", "统一信用代码已属于其他客商编号")
                receipt["action"] = "reject"
                continue
            if id_match.status != "active":
                self._row_error(receipt, "counterparty_id", "COUNTERPARTY_ARCHIVED", "已归档客商不能通过批量导入恢复")
                receipt["action"] = "reject"
                continue
            if strategy == "reject":
                self._row_error(receipt, "counterparty_id", "COUNTERPARTY_EXISTS", "当前租户已存在该客商")
                receipt["action"] = "reject"
                continue
            action = strategy
            row["_import_action"] = receipt["action"] = action
            row["_expected_row_version"] = id_match.row_version
            row["_expected_profile_hash"] = id_match.profile_hash
            if action == "skip":
                receipt["warnings"].append({"code": "EXISTING_RECORD_SKIPPED", "message": "按批次策略保留现有客商，不写入本行"})

    def _normalize_rows(self, raw_rows: list[dict], file_format: str, mapping: dict, parse_receipts: list[dict]) -> tuple[list[dict], list[dict]]:
        normalized: list[dict] = []
        receipts: list[dict] = []
        mapped_sources = set(mapping)
        for index, source in enumerate(raw_rows):
            row_number = index + (2 if file_format == "csv" else 1)
            receipt = {"row_number": row_number, "counterparty_id": None, "credit_code": None, "action": "reject", "errors": [], "warnings": []}
            if index < len(parse_receipts):
                receipt["errors"].extend(parse_receipts[index].get("errors", []))
            try:
                candidate: dict[str, Any] = {}
                for key in CANONICAL_FIELDS:
                    source_key = "id" if key == "counterparty_id" and "counterparty_id" not in source and "id" in source else key
                    if source_key in source:
                        value = self._coerce(key, source[source_key])
                        if value is not None:
                            candidate[key] = value
                extensions = deepcopy(candidate.get("extensions") or {})
                for key, value in source.items():
                    if key not in CANONICAL_FIELDS and key != "id" and key not in mapped_sources:
                        extensions[key] = deepcopy(value)
                        if file_format == "csv":
                            receipt["warnings"].append({"code": "UNMAPPED_COLUMN_PRESERVED", "message": f"未映射列 {key} 已保存到扩展字段"})
                if extensions:
                    candidate["extensions"] = extensions
                for source_path, target_path in mapping.items():
                    value, found = self._get_path(source, source_path)
                    if found:
                        target = "counterparty_id" if target_path == "id" else target_path
                        coerced = self._coerce(target, value)
                        if coerced is not None:
                            self._set_path(candidate, target, coerced)
                candidate["reason"] = "客商批量导入记录预检"
                model = CounterpartyCreate.model_validate(candidate)
                item = model.model_dump(exclude={"reason"})
                receipt["counterparty_id"] = item["counterparty_id"]
                receipt["credit_code"] = item["credit_code"]
                normalized.append(item)
            except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
                if isinstance(exc, ValidationError):
                    for error in exc.errors(include_url=False, include_context=False):
                        self._row_error(receipt, ".".join(str(part) for part in error["loc"]), error["type"].upper(), error["msg"])
                else:
                    self._row_error(receipt, "row", "ROW_NORMALIZATION_FAILED", str(exc))
                normalized.append({})
            receipts.append(receipt)
        return normalized, receipts

    @staticmethod
    def _parse(content: str, file_format: str) -> tuple[list[dict], list[dict]]:
        if file_format == "json":
            try:
                document = json.loads(content, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"不允许数值 {value}")))
            except (json.JSONDecodeError, ValueError) as exc:
                raise CounterpartyImportError("COUNTERPARTY_IMPORT_PARSE_FAILED", f"JSON 解析失败：{exc}", 422) from exc
            rows = document.get("records") if isinstance(document, dict) else document
            if not isinstance(rows, list) or not rows:
                raise CounterpartyImportError("COUNTERPARTY_IMPORT_EMPTY", "JSON 必须是非空记录数组或包含 records 数组", 422)
            if not all(isinstance(row, dict) for row in rows):
                raise CounterpartyImportError("COUNTERPARTY_IMPORT_PARSE_FAILED", "JSON 数组中的每条记录必须是对象", 422)
            return rows, [{} for _ in rows]

        reader = csv.DictReader(io.StringIO(content, newline=""))
        headers = reader.fieldnames or []
        if not headers:
            raise CounterpartyImportError("COUNTERPARTY_IMPORT_EMPTY", "CSV 缺少表头", 422)
        if len(headers) != len(set(headers)) or any(not str(header).strip() for header in headers):
            raise CounterpartyImportError("COUNTERPARTY_IMPORT_INVALID_HEADER", "CSV 表头不能为空或重复", 422)
        rows = list(reader)
        if not rows:
            raise CounterpartyImportError("COUNTERPARTY_IMPORT_EMPTY", "CSV 不包含数据行", 422)
        receipts = []
        for row in rows:
            errors = []
            if None in row:
                errors.append({"field": "row", "code": "CSV_EXTRA_COLUMNS", "message": "数据列数超过表头列数"})
                row.pop(None, None)
            receipts.append({"errors": errors})
        return rows, receipts

    @staticmethod
    def _coerce(target: str, value: Any) -> Any:
        root = target.split(".", 1)[0]
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                return None
        if root in BOOLEAN_FIELDS and isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "1", "yes", "y", "是"}:
                return True
            if lowered in {"false", "0", "no", "n", "否"}:
                return False
        if root in NUMERIC_FIELDS and isinstance(value, str):
            return float(value.replace(",", ""))
        if root in INTEGER_FIELDS and isinstance(value, str):
            return int(value)
        if root in {"external", "internal", "financial", "extensions"} and "." not in target and isinstance(value, str):
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError(f"{root} 必须是 JSON 对象")
            return parsed
        return value

    @staticmethod
    def _get_path(source: dict, path: str) -> tuple[Any, bool]:
        current: Any = source
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None, False
            current = current[part]
        return current, True

    @staticmethod
    def _set_path(target: dict, path: str, value: Any) -> None:
        parts = path.split(".")
        current = target
        for part in parts[:-1]:
            child = current.setdefault(part, {})
            if not isinstance(child, dict):
                raise ValueError(f"字段映射目标冲突：{path}")
            current = child
        current[parts[-1]] = value

    @staticmethod
    def _row_error(receipt: dict, field: str, code: str, message: str) -> None:
        receipt["errors"].append({"field": field, "code": code, "message": message})

    def _record(self, tenant_id: str, batch_id: str) -> CounterpartyImportBatchRecord:
        record = self.session.scalars(
            select(CounterpartyImportBatchRecord).where(
                CounterpartyImportBatchRecord.tenant_id == tenant_id,
                CounterpartyImportBatchRecord.id == batch_id,
            )
        ).first()
        if record is None:
            raise CounterpartyImportError("COUNTERPARTY_IMPORT_NOT_FOUND", "客商导入批次不存在", 404)
        return record

    def _find_collision(self, tenant_id: str, row: dict) -> CounterpartyRecord | None:
        return self.session.scalars(
            select(CounterpartyRecord).where(
                CounterpartyRecord.tenant_id == tenant_id,
                or_(CounterpartyRecord.counterparty_id == row["counterparty_id"], CounterpartyRecord.credit_code == row["credit_code"]),
            )
        ).first()

    def _existing_by_id(self, tenant_id: str, counterparty_id: str) -> CounterpartyRecord | None:
        return self.session.scalars(select(CounterpartyRecord).where(
            CounterpartyRecord.tenant_id == tenant_id, CounterpartyRecord.counterparty_id == counterparty_id
        )).first()

    def _existing_by_code(self, tenant_id: str, credit_code: str) -> CounterpartyRecord | None:
        return self.session.scalars(select(CounterpartyRecord).where(
            CounterpartyRecord.tenant_id == tenant_id, CounterpartyRecord.credit_code == credit_code
        )).first()

    @staticmethod
    def _new_counterparty(batch: CounterpartyImportBatchRecord, values: dict, principal: "Principal") -> CounterpartyRecord:
        record = CounterpartyRecord(
            id=str(uuid4()), tenant_id=batch.tenant_id, counterparty_id=values["counterparty_id"],
            credit_code=values["credit_code"], name=values["name"], counterparty_type=values["counterparty_type"],
            industry=values["industry"], cooperation_status=values["cooperation_status"],
            is_key_counterparty=values["is_key_counterparty"], requested_limit=Decimal(str(values["requested_limit"])),
            current_limit=Decimal(str(values["current_limit"])), current_payment_term_days=values["current_payment_term_days"],
            current_rating=values.get("current_rating"), current_segment=values.get("current_segment"),
            external_json=deepcopy(values["external"]), internal_json=deepcopy(values["internal"]),
            financial_json=deepcopy(values["financial"]), extensions_json=deepcopy(values["extensions"]),
            profile_hash="", status="active", source_type="batch_import", created_by=principal.subject,
            updated_by=principal.subject,
        )
        record.profile_hash = CounterpartyRepository._profile_hash(record)
        return record

    @staticmethod
    def _apply_values(record: CounterpartyRecord, values: dict) -> None:
        for field in (
            "credit_code", "name", "counterparty_type", "industry", "cooperation_status",
            "is_key_counterparty", "current_payment_term_days", "current_rating", "current_segment",
        ):
            setattr(record, field, deepcopy(values.get(field)))
        record.requested_limit = Decimal(str(values["requested_limit"]))
        record.current_limit = Decimal(str(values["current_limit"]))
        record.external_json = deepcopy(values["external"])
        record.internal_json = deepcopy(values["internal"])
        record.financial_json = deepcopy(values["financial"])
        record.extensions_json = deepcopy(values["extensions"])

    @staticmethod
    def _preview_hash(record: CounterpartyImportBatchRecord) -> str:
        return content_hash({
            "tenant_id": record.tenant_id, "import_key": record.import_key, "source_hash": record.source_hash,
            "duplicate_strategy": record.duplicate_strategy, "field_mapping": record.field_mapping_json or {},
            "normalized_rows": record.normalized_rows_json or [], "row_receipts": record.row_receipts_json or [],
            "counts": {"total": record.total_count, "valid": record.valid_count, "invalid": record.invalid_count,
                       "create": record.create_count, "update": record.update_count, "skip": record.skip_count},
        })

    @staticmethod
    def _audit_payload(record: CounterpartyImportBatchRecord, principal: "Principal", reason: str) -> dict:
        return {
            "tenant_id": record.tenant_id, "import_id": record.id, "import_key": record.import_key,
            "actor_name": principal.name, "reason": reason, "status": record.status,
            "file_name": record.file_name, "file_format": record.file_format,
            "duplicate_strategy": record.duplicate_strategy, "source_hash": record.source_hash,
            "preview_hash": record.preview_hash, "total_count": record.total_count,
            "valid_count": record.valid_count, "invalid_count": record.invalid_count,
            "create_count": record.create_count, "update_count": record.update_count,
            "skip_count": record.skip_count, "committed_count": record.committed_count,
        }

    @staticmethod
    def _view(record: CounterpartyImportBatchRecord, *, idempotent: bool = False) -> dict:
        iso = lambda value: value.isoformat() if value else None
        return {
            "id": record.id, "tenant_id": record.tenant_id, "import_key": record.import_key,
            "file_name": record.file_name, "file_format": record.file_format,
            "duplicate_strategy": record.duplicate_strategy, "field_mapping": deepcopy(record.field_mapping_json or {}),
            "source_hash": record.source_hash, "request_hash": record.request_hash, "preview_hash": record.preview_hash,
            "status": record.status, "total_count": record.total_count, "valid_count": record.valid_count,
            "invalid_count": record.invalid_count, "create_count": record.create_count,
            "update_count": record.update_count, "skip_count": record.skip_count,
            "committed_count": record.committed_count, "row_receipts": deepcopy(record.row_receipts_json or []),
            "precheck_reason": record.precheck_reason, "commit_reason": record.commit_reason,
            "created_by": record.created_by, "created_by_name": record.created_by_name,
            "committed_by": record.committed_by, "committed_by_name": record.committed_by_name,
            "committed_at": iso(record.committed_at), "row_version": record.row_version,
            "created_at": iso(record.created_at), "updated_at": iso(record.updated_at), "idempotent": idempotent,
        }
