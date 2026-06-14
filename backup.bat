@echo off
REM ============================================================
REM  Watsu Gift Voucher System — Daily Backup
REM  Scheduled task: daily at 23:00
REM  Target: OneDrive\Technical\Claude_Projects\Voucher\backup\
REM ============================================================

SET SRC=T:\Voucher
SET DST=T:\Voucher\backup

echo [%date% %time%] Starting backup...

REM Back up generated voucher files (PDFs, QR images, metadata)
robocopy "%SRC%\vouchers" "%DST%\vouchers" /MIR /R:2 /W:5 /NP /LOG+:"%DST%\backup.log"

REM Back up the SQLite database
robocopy "%SRC%" "%DST%" *.db /R:2 /W:5 /NP /LOG+:"%DST%\backup.log"

echo [%date% %time%] Backup complete.
