from datetime import datetime

from sqlalchemy import and_, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.models.clinical_record import ClinicalRecord
from app.models.pain_entry import PainEntry
from app.models.prescription import Prescription, PrescriptionCompletion
from app.schemas.history import HistoryCategory


def events(
    db: Session, patient_id: str, category: HistoryCategory | None, start: datetime | None,
    end: datetime | None, position: tuple[datetime, str] | None, limit: int,
):
    sources = []
    if category in (None, HistoryCategory.PAIN):
        sources.append(project(
            PainEntry.id, PainEntry.occurred_at, HistoryCategory.PAIN,
            "Registro de dor", PainEntry.description, PainEntry.intensity, PainEntry.region,
        ).where(PainEntry.patient_id == patient_id))
    if category in (None, HistoryCategory.CLINICAL_RECORD):
        sources.append(project(
            ClinicalRecord.id, ClinicalRecord.finalized_at, HistoryCategory.CLINICAL_RECORD,
            "Prontuário clínico", literal(None), ClinicalRecord.pain_intensity, ClinicalRecord.body_region,
        ).where(ClinicalRecord.patient_id == patient_id, ClinicalRecord.status == "finalized"))
    if category in (None, HistoryCategory.EXERCISE):
        sources.append(project(
            PrescriptionCompletion.id, PrescriptionCompletion.completed_at, HistoryCategory.EXERCISE,
            "Exercício concluído", Prescription.title, literal(None), literal(None),
        ).join(Prescription).where(Prescription.patient_id == patient_id))
    if not sources:
        return []
    history = union_all(*sources).subquery()
    query = page(select(history), history.c, start, end, position).limit(limit + 1)
    return db.execute(query).mappings().all()


def finalized_times(db: Session, patient_id: str, start: datetime, end: datetime):
    return db.scalars(select(ClinicalRecord.finalized_at).where(
        ClinicalRecord.patient_id == patient_id,
        ClinicalRecord.status == "finalized",
        ClinicalRecord.finalized_at >= start,
        ClinicalRecord.finalized_at < end,
    ).execution_options(yield_per=512))


def project(id_column, timestamp, category, title, summary, intensity, region):
    return select(
        id_column.label("id"), timestamp.label("occurred_at"), literal(category.value).label("category"),
        literal(title).label("title"), summary.label("summary"), intensity.label("intensity"),
        region.label("region"),
    )


def page(query, columns, start, end, position):
    if start is not None:
        query = query.where(columns.occurred_at >= start)
    if end is not None:
        query = query.where(columns.occurred_at < end)
    if position is not None:
        timestamp, entry_id = position
        query = query.where(or_(
            columns.occurred_at < timestamp,
            and_(columns.occurred_at == timestamp, columns.id < entry_id),
        ))
    return query.order_by(columns.occurred_at.desc(), columns.id.desc())
