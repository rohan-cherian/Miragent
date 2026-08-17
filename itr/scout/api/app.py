# Emptied deliberately — this package is reserved for the console API
# (Slice-1 Task 24, Sutej). The Gmail ingestion API that used to live here
# moved to scout/gmail/ingest_api.py, because the Task 4 layering lint
# forbids scout/api/ from importing scout.gmail.
#
# Run the ingestion service with:
#   poetry run uvicorn scout.gmail.ingest_api:create_app --factory --port 8092
