# Baseline execution evidence

Executed 2026-11-04 on Windows x64, CPython 3.11.9.

Command: `.venv/Scripts/python.exe run_headless.py`

Observed completion: 200 simulated seconds; final monitor sample 199.5; no Traceback/Error/Exception text in captured console output.

Output evidence (nonempty CSV records, including header):
- buffer.csv: 430508 bytes; 5824 nonempty records.
- can_bus.csv: 2222263 bytes; 17948 nonempty records.
- checkpoints.csv: 1552190 bytes; 6106 nonempty records.

Observed checkpoint tags:

- MonitorTags.CP_ECU_CREATED_ECU_KEY_REG_MESSAGE
- MonitorTags.CP_ECU_DECRYPTED_CONF_MESSAGE
- MonitorTags.CP_ECU_DECRYPTED_GRANT_MESSAGE
- MonitorTags.CP_ECU_DECRYPTED_SIMPLE_MESSAGE
- MonitorTags.CP_ECU_ENCRYPTED_INNER_REG_MESSAGE
- MonitorTags.CP_ECU_ENCRYPTED_OUTER_REG_MESSAGE
- MonitorTags.CP_ECU_ENCRYPTED_REQ_MESSAGE
- MonitorTags.CP_ECU_ENCRYPTED_SEND_SIMPLE_MESSAGE
- MonitorTags.CP_ECU_HASHED_INNER_REG_MESSAGE
- MonitorTags.CP_ECU_INTENT_SEND_SIMPLE_MESSAGE
- MonitorTags.CP_ECU_RECEIVE_CONF_MESSAGE
- MonitorTags.CP_ECU_RECEIVE_GRANT_MESSAGE
- MonitorTags.CP_ECU_RECEIVE_SEC_MOD_ADVERTISEMENT
- MonitorTags.CP_ECU_RECEIVE_SIMPLE_MESSAGE
- MonitorTags.CP_ECU_SEND_REG_MESSAGE
- MonitorTags.CP_ECU_START_CREATE_REQ_MESSAGE
- MonitorTags.CP_ECU_START_CREATION_REG_MESSAGE
- MonitorTags.CP_ECU_VALIDATED_SEC_MOD_CERTIFICATE
- MonitorTags.CP_SEC_COMPARED_HASH_REG_MSG
- MonitorTags.CP_SEC_CREATED_CMP_HASH_REG_MSG
- MonitorTags.CP_SEC_DECRYPTED_INNER_REG_MESSAGE
- MonitorTags.CP_SEC_DECRYPTED_OUTER_REG_MESSAGE
- MonitorTags.CP_SEC_DECRYPTED_REQ_MESSAGE
- MonitorTags.CP_SEC_ECNRYPTED_CONFIRMATION_MESSAGE
- MonitorTags.CP_SEC_ENCRYPTED_GRANT_MESSAGE
- MonitorTags.CP_SEC_GENERATED_SESSION_KEY
- MonitorTags.CP_SEC_INIT_AUTHENTICATION
- MonitorTags.CP_SEC_RECEIVE_REG_MESSAGE
- MonitorTags.CP_SEC_RECEIVE_REQ_MESSAGE
- MonitorTags.CP_SEC_VALIDATED_ECU_CERTIFICATE

Console completion:
```
Current time 198.5 
Current time 199.0 
Current time 199.5 
Time elapsed: 1.674818515777588 seconds
BufferInterpreter finish!
Started Export...
EventlineInterpreter finish!
```
Repeated execution after final source edits: exit code 0, final monitor time 199.5, completion/export messages observed. `pip check`: no broken requirements.

Tracked upstream CSV samples were restored after inspection to avoid committing generated output; rerun the command to regenerate results.
