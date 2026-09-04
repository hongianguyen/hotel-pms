#!/usr/bin/env bash
# Y Lak menu + inventory import. Run order matters -- see README.md.
#
#   ./run.sh extract              rebuild the JSON from sources/ (offline)
#   ./run.sh load   [test|prod]   push and load onto a server
#   ./run.sh purge  [test|prod]   delete the pre-toolchain POS menu and BoMs
#   ./run.sh verify [test|prod]   read-only assertions
#   ./run.sh english [test|prod]  bilingual POS names + English descriptions
#   ./run.sh smoke  [test]        ring a POS order, assert kits explode, roll back
#
# Default target is test. `prod` is the live hotel database -- back it up first.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE=/opt/ylak

case "${2:-test}" in
test|103.200.20.13)
    TARGET=test
    HOST=103.200.20.13
    CONF=/opt/hotel-pms-test/odoo-test.conf
    DB=hotel_pms_test
    ODOO=/opt/odoo/odoo-bin
    ;;
prod|14.225.192.16)
    TARGET=prod
    HOST=14.225.192.16
    CONF=/etc/odoo.conf
    DB=hotel_db
    # NOT /opt/odoo/odoo-bin -- that path is the test server's layout.
    ODOO=/opt/odoo/odoo/odoo-bin
    ;;
*)
    echo "unknown target '${2}' -- use 'test' or 'prod'" >&2
    exit 1
    ;;
esac

SSH="ssh -i $HOME/.ssh/id_ed25519 -o StrictHostKeyChecking=no root@$HOST"

# Restarting differs per host and getting it wrong is the worst failure mode
# available here. Test has no systemd unit, so it is killed by port and
# restarted by hand. Production runs under `odoo.service`; using the test
# recipe there would kill nothing (prod is on 8069, not 8075) and then start a
# SECOND worker set beside the running one -- two cron runners against live
# books, i.e. the night audit posting twice.
restart_odoo() {
    if [ "$TARGET" = prod ]; then
        echo "--- systemctl restart odoo ($HOST)"
        $SSH "systemctl restart odoo && sleep 12 && systemctl is-active odoo"
    else
        echo "--- restart odoo ($HOST, no systemd unit)"
        $SSH "fuser -k 8075/tcp 2>/dev/null; sleep 4; \
              nohup sudo -u odoo /opt/odoo/venv/bin/python3 $ODOO \
              -c $CONF -d $DB > /dev/null 2>&1 & sleep 12" || true
    fi
}

shell_env="YLAK_DIR=$REMOTE \
  YLAK_DATA=$REMOTE/menu_data.json \
  YLAK_INVENTORY=$REMOTE/inventory_data.json \
  YLAK_SETS=$REMOTE/sets_data.json"

run_step() {   # run_step <script>
    echo "--- $1"
    # shellcheck disable=SC2086
    $SSH "cd $REMOTE && $shell_env sudo -u odoo -E /opt/odoo/venv/bin/python3 \
        $ODOO shell -c $CONF -d $DB --no-http --logfile=/dev/null < $REMOTE/$1"
}

push() {
    tar czf /tmp/ylak-tools.tar.gz -C "$HERE" \
        $(cd "$HERE" && ls *.py *.json *.csv sources/*.md sources/README.md)
    scp -i "$HOME/.ssh/id_ed25519" -o StrictHostKeyChecking=no \
        /tmp/ylak-tools.tar.gz "root@$HOST:/root/" >/dev/null
    $SSH "mkdir -p $REMOTE && tar xzf /root/ylak-tools.tar.gz -C $REMOTE/ \
          && chown -R odoo:odoo $REMOTE"
}

case "${1:-}" in
extract)
    cd "$HERE"
    python3 extract_menu.py
    # Merges the later `extra Cost_ingredients` sheet INTO menu_data.json, so
    # it must run after extract_menu.py (which writes that file) and before
    # extract_sets.py (which resolves set courses against it).
    python3 extract_extra.py
    python3 extract_sets.py || echo "(sets reported gaps -- see above)"
    python3 extract_inventory.py
    ;;
load)
    echo "### target=$TARGET host=$HOST db=$DB"
    push
    # Step 0 runs in its OWN process and exits 2 if it changed anything: the
    # decimal.precision value is cached per process, so bumping it and then
    # writing BoM lines in the same process stores 0.075 as 0.08.
    if ! run_step load_00_precision.py; then
        echo
        echo "Precision or groups changed -- restarting Odoo before the load."
        restart_odoo
        echo "Restarted. Continuing load."
    fi
    run_step load_10_catalog.py
    run_step load_20_sets.py
    # Hard gate. Exits 3 if any category the loader owns uses real-time stock
    # valuation, in which case the opening count below would post a journal
    # entry per line into the live books. `set -e` turns that into an abort.
    run_step load_25_valuation_gate.py
    run_step load_30_inventory.py
    # No-op until the owner fills in reorder_levels.csv.
    run_step load_40_orderpoints.py
    # Prune LAST: it retires anything the extracts do not account for, so
    # every creating step must have run first.
    run_step load_15_prune.py
    # After the prune, and after load_10_catalog.py: that step rewrites `name`
    # from menu_data.json on every dish it owns, stripping the English half
    # back off. This puts it back.
    run_step load_50_english.py
    echo
    echo "Loaded. Now: ./run.sh verify $TARGET"
    ;;
verify)
    push
    run_step verify.py
    ;;
english)
    # Names and descriptions only -- touches no price, no BoM and no stock.
    # Writes english_backup.json on the server the first time it runs; that
    # file is the pre-English state and is what a revert reads.
    push
    run_step load_50_english.py
    ;;
purge)
    # Deletes the hand-made POS products and BoMs that predate this toolchain,
    # so the import lands without case-duplicates. Refuses to run once the
    # import owns POS products -- see the script's own rails.
    push
    run_step prod_05_purge.py
    echo
    echo "Purged. Now: ./run.sh load $TARGET"
    ;;
smoke)
    # Rings real orders in a real POS session. It rolls back, but "roll back an
    # order I just wrote into the live till" is not a bet worth taking: test
    # carries the same module set (mrp, pos_mrp, stock_account,
    # hotel_pos_folio), so the explosion proof from test transfers to prod.
    if [ "$TARGET" = prod ]; then
        echo "smoke is refused on prod -- it writes real POS orders." >&2
        exit 1
    fi
    push
    run_step smoke_pos.py
    ;;
*)
    sed -n '2,10p' "${BASH_SOURCE[0]}"
    exit 1
    ;;
esac
