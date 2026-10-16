-- A command's live output is a stream on the shared cache, and its result
-- holds it whole, so the exec relay's parts table goes with what it held.

DROP TABLE core.exec_parts;
