/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * Dates on this board are hotel business dates, so they must be read in the
 * hotel's own timezone — never UTC.
 *
 * `new Date().toISOString()` converts to UTC first: at 01:00 in UTC+7 that
 * is still 18:00 the previous day, so the night shift (00:00–07:00) opened
 * the board on yesterday. And `new Date("2026-08-29")` parses as UTC
 * midnight, which is a different calendar day west of Greenwich.
 */
function localISODate(d) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Parse a YYYY-MM-DD business date as local midnight, not UTC midnight. */
function parseISODate(s) {
    const [y, m, d] = String(s).split("-").map(Number);
    return new Date(y, m - 1, d);
}

export class ReceptionDashboard extends Component {
    static template = "hotel_reporting.ReceptionDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            kpis: {},
            gantt: { rooms: [], reservations: [], dates: [] },
            loading: true,
            ganttStartDate: localISODate(new Date()),
        });
        this.dragResId = null;

        onWillStart(async () => {
            await this.loadData();
        });

        // Spec 1.2: reads may be cached up to 30s -> poll every 30s so the
        // board stays near-live without manual refreshes.
        this.refreshTimer = setInterval(() => this.loadData(), 30000);
        onWillUnmount(() => clearInterval(this.refreshTimer));
    }

    async loadData() {
        this.state.loading = true;
        try {
            const [kpis, gantt] = await Promise.all([
                this.orm.call("hotel.dashboard", "get_reception_kpis", []),
                this.orm.call("hotel.dashboard", "get_gantt_data", [this.state.ganttStartDate]),
            ]);
            this.state.kpis = kpis;
            this.state.gantt = gantt;
        } catch (e) {
            console.error("Failed to load dashboard data:", e);
        }
        this.state.loading = false;
    }

    async onRefresh() {
        await this.loadData();
    }

    onPrevPeriod() {
        const d = parseISODate(this.state.ganttStartDate);
        d.setDate(d.getDate() - 15);
        this.state.ganttStartDate = localISODate(d);
        this.loadData();
    }

    onNextPeriod() {
        const d = parseISODate(this.state.ganttStartDate);
        d.setDate(d.getDate() + 15);
        this.state.ganttStartDate = localISODate(d);
        this.loadData();
    }

    onGanttCellClick(roomId, seg) {
        if (seg.type !== 'empty') return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hotel.reservation",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_room_id: roomId,
                default_checkin_date: seg.date,
            },
        }, {
            onClose: () => this.loadData(),
        });
    }

    getGanttRowSegments(roomId) {
        const dates = this.state.gantt.dates;
        const segments = [];
        let i = 0;
        while (i < dates.length) {
            const d = dates[i];
            // All bookings covering this cell, not just the first: the
            // backend already sorts by priority (conflicts first), so [0]
            // is the bar to show and the rest are double-bookings that
            // must stay visible instead of being silently hidden.
            const covering = this.state.gantt.reservations.filter(
                (r) => r.room_id === roomId &&
                    r.checkin_date <= d.date &&
                    r.checkout_date > d.date
            );
            const res = covering[0];
            const overlaps = covering.slice(1);
            if (res) {
                let colspan = 0;
                while (i + colspan < dates.length) {
                    const nd = dates[i + colspan].date;
                    if (nd >= res.checkin_date && nd < res.checkout_date) {
                        colspan++;
                    } else {
                        break;
                    }
                }
                segments.push({
                    type: 'reservation',
                    date: d.date,
                    is_weekend: d.is_weekend,
                    is_past: d.is_past,
                    colspan: colspan,
                    res: res,
                    overlaps: overlaps,
                    overlap_title: overlaps.length
                        ? overlaps.map(
                            (r) => `${r.reservation_number} — ${r.guest_name}`
                          ).join('\n')
                        : '',
                });
                i += colspan;
            } else {
                segments.push({
                    type: 'empty',
                    date: d.date,
                    is_weekend: d.is_weekend,
                    is_past: d.is_past,
                    colspan: 1,
                });
                i++;
            }
        }
        return segments;
    }

    openReservation(resId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hotel.reservation",
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    onDragStart(ev, resId) {
        this.dragResId = resId;
        ev.dataTransfer.effectAllowed = "move";
    }

    onDragOver(ev) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
        ev.currentTarget.classList.add("drag-over");
    }

    onDragLeave(ev) {
        ev.currentTarget.classList.remove("drag-over");
    }

    async onDrop(ev, roomId, dateStr) {
        ev.preventDefault();
        ev.currentTarget.classList.remove("drag-over");
        const resId = this.dragResId;
        this.dragResId = null;
        if (!resId) return;

        const res = this.state.gantt.reservations.find((r) => r.id === resId);
        if (!res) return;

        // Only pre-arrival bookings can be moved by dragging. An in-house or
        // departed stay has room charges already posted and its room flagged
        // occupied; the server refuses the write, so do not pretend otherwise.
        if (!this.isDraggable(res)) {
            this.notification.add(
                `${res.reservation_number} is ${res.state.replace("_", " ")} ` +
                `and cannot be moved from the board. Open the reservation to ` +
                `amend it.`,
                { type: "warning" }
            );
            return;
        }

        // Keep same number of nights, shift to dropped date
        const nights = Math.round(
            (parseISODate(res.checkout_date) - parseISODate(res.checkin_date)) /
            (1000 * 60 * 60 * 24)
        );
        const newCheckin = parseISODate(dateStr);
        const newCheckout = parseISODate(dateStr);
        newCheckout.setDate(newCheckout.getDate() + nights);
        const fmt = localISODate;

        try {
            await this.orm.write("hotel.reservation", [resId], {
                room_id: roomId,
                checkin_date: fmt(newCheckin),
                checkout_date: fmt(newCheckout),
            });
            await this.loadData();
        } catch (e) {
            // The server rejects overlaps and locked stays. Surface the
            // reason and reload, otherwise staff believe the move happened.
            const msg =
                e?.data?.message || e?.message || "The move was rejected.";
            this.notification.add(msg, {
                type: "danger",
                title: "Could not move reservation",
            });
            await this.loadData();
        }
    }

    /** Pre-arrival stays only: in-house/departed bookings are server-locked. */
    isDraggable(res) {
        return res.state === "draft" || res.state === "confirmed";
    }

    /** Bar tooltip: guest, plus any double-booking hidden behind this bar. */
    barTitle(seg) {
        let title = seg.res.guest_name;
        if (seg.res.payment_issue) {
            title += " — unpaid balance";
        }
        if (seg.overlaps.length) {
            title += `\n⚠ Double-booked with:\n${seg.overlap_title}`;
        }
        return title;
    }

    formatCurrency(value) {
        if (!value) return "0";
        return new Intl.NumberFormat("vi-VN").format(Math.round(value));
    }

    getCurrentDate() {
        return new Date().toLocaleDateString("en-GB", {
            weekday: "long", year: "numeric", month: "long", day: "numeric"
        });
    }
}

registry.category("actions").add("hotel_reception_dashboard", ReceptionDashboard);
