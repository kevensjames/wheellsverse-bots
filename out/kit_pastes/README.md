# Toodle — Kit Sequence Pastes

Each subdirectory below corresponds to one Kit sequence. Open each
`.txt` file in order, copy the SUBJECT line into Kit's subject field,
and copy everything under BODY into Kit's body field. Set the delay
shown in the file header.

Sequences must be created in Kit's UI first (no API for that). The
name in Kit MUST match the env var below — case-insensitive lookup,
but spaces and word boundaries count.

| Sequence name in Kit | Env var | Files |
| --- | --- | --- |
| KDP Launch | `KIT_SEQUENCE_KDP_NAME` | 01_email_1_immediate_deliver_the_magnet.txt, 02_email_2_day_1_the_why_the_shift.txt, 03_email_3_day_3_teach_something_real.txt, 04_email_4_day_5_proof_soft_pitch.txt, 05_email_5_day_7_direct_offer_close.txt |
| Welcome | `KIT_SEQUENCE_WELCOME_NAME` | 01_email_1_immediate.txt, 02_email_2_day_2.txt |
| KDP Long-Tail | `KIT_SEQUENCE_KDP_LONGTAIL_NAME` | 01_email_6_day_14_case_study_proof_through_.txt, 02_email_7_day_21_objection_but_my_situatio.txt, 03_email_8_day_30_last_call_direct_kind_cle.txt |

## After pasting

Run the verifier to confirm Kit resolves all three by name:

```bash
/Users/jhonwheeler/wheellsverse_venv/bin/python scripts/toodle_kit_check.py
```

Exit 0 = ready to flip `KIT_DRY_RUN=false`. Exit 1 = one or more
sequences missing (the verifier prints which).
