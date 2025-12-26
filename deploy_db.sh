#!/bin/bash
echo "Uploading database to Fly.io..."
fly ssh console -C "rm -f /data/jobs.db"
echo "put jobs.db /data/jobs.db" | fly ssh sftp shell
echo "Done!"
