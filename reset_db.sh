#!/bin/bash
set -e
sudo -u odoo psql -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='hotel_pms_test' AND pid != pg_backend_pid();"
sudo -u odoo psql -d postgres -c "DROP DATABASE IF EXISTS hotel_pms_test;"
sudo -u odoo createdb hotel_pms_test
echo "DB_RECREATED"
