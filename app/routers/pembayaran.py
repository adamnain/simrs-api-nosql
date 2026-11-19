from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.cache import bump_report
from app.database import get_db

router = APIRouter(prefix="/api/pembayaran", tags=["pembayaran"])


class StatusBaru(BaseModel):
    status: Literal["Berhasil"]


@router.patch("/{no_billing}/status")
def pembayaran_berhasil(no_billing: str, body: StatusBaru, db=Depends(get_db)):
    payment = db.pembayaran.find_one({"no_billing": no_billing})

    if payment is None:
        raise HTTPException(status_code=404, detail="pembayaran tidak ditemukan")

    if db.pembayaran.find_one({"no_registrasi": payment["no_registrasi"], "status_pembayaran": body.status,
                               "no_billing": {"$ne": no_billing}}) is not None:
        raise HTTPException(status_code=409, detail="pendaftaran ini sudah dibayar")

    db.pembayaran.update_one({"no_billing": no_billing}, {"$set": {"status_pembayaran": body.status}})

    bump_report("pendapatan")
    return {"no_billing": no_billing, "status_pembayaran": body.status}
