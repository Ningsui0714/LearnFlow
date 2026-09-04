#!/bin/bash

set -u
mkdir -p /logs/verifier

python3 /tests/test_outputs.py --calibrate
calibration_status=$?
if [ "$calibration_status" -ne 0 ]; then
  exit "$calibration_status"
fi

python3 /tests/test_outputs.py
verification_status=$?
if [ "$verification_status" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
  exit 0
fi
if [ "$verification_status" -eq 10 ]; then
  echo 0 > /logs/verifier/reward.txt
  exit 0
fi

exit "$verification_status"
