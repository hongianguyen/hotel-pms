#!/bin/bash
# ════════════════════════════════════════════════════════════════
# Hotel PMS — Deploy to VPS
# ════════════════════════════════════════════════════════════════
# Usage: ./deploy.sh <vps_host> [odoo_db]
# Example: ./deploy.sh root@your-vps.com hotel_db

set -e

VPS_HOST=${1:?"Usage: ./deploy.sh <vps_host> [odoo_db]"}
DB_NAME=${2:-"hotel_db"}
REMOTE_ADDONS="/opt/odoo/custom_addons"

MODULES="hotel_core,hotel_frontdesk,hotel_housekeeping,hotel_revenue_basic,hotel_services,hotel_reporting,hotel_night_audit"

echo "🚀 Deploying Hotel PMS to $VPS_HOST..."

# Step 1: Sync addons
echo "📦 Syncing addons..."
rsync -avz --delete \
    addons/hotel_core \
    addons/hotel_frontdesk \
    addons/hotel_housekeeping \
    addons/hotel_revenue_basic \
    addons/hotel_services \
    addons/hotel_reporting \
    addons/hotel_night_audit \
    "$VPS_HOST:$REMOTE_ADDONS/"

# Step 2: Upgrade modules
echo "🔄 Upgrading Odoo modules..."
ssh "$VPS_HOST" "cd /opt/odoo && python3 odoo-bin -d $DB_NAME -u $MODULES --stop-after-init"

# Step 3: Restart Odoo
echo "♻️ Restarting Odoo..."
ssh "$VPS_HOST" "systemctl restart odoo"

echo "✅ Deployment complete!"
echo "   Database: $DB_NAME"
echo "   Modules: $MODULES"
