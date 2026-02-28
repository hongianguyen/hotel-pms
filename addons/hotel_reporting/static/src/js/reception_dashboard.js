/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class ReceptionDashboard extends Component {
    static template = "hotel_reporting.ReceptionDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            kpis: {},
            rooms: [],
            gantt: { rooms: [], reservations: [], dates: [] },
            loading: true,
        });
        this.dragResId = null;

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.loading = true;
        try {
            const [kpis, rooms, gantt] = await Promise.all([
                this.orm.call("hotel.dashboard", "get_reception_kpis", []),
                this.orm.call("hotel.dashboard", "get_room_status_board", []),
                this.orm.call("hotel.dashboard", "get_gantt_data", []),
            ]);
            this.state.kpis = kpis;
            this.state.rooms = rooms;
            this.state.gantt = gantt;
        } catch (e) {
            console.error("Failed to load dashboard data:", e);
        }
        this.state.loading = false;
    }

    async onRefresh() {
        await this.loadData();
    }

    getGanttCellContent(roomId, dateStr) {
        const res = this.state.gantt.reservations.find(
            (r) => r.room_id === roomId &&
                r.checkin_date <= dateStr &&
                r.checkout_date > dateStr
        );
        return res || null;
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

    openRoom(roomId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hotel.room",
            res_id: roomId,
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

        // Keep same number of nights, shift to dropped date
        const nights = Math.round(
            (new Date(res.checkout_date) - new Date(res.checkin_date)) /
            (1000 * 60 * 60 * 24)
        );
        const newCheckin = new Date(dateStr);
        const newCheckout = new Date(dateStr);
        newCheckout.setDate(newCheckout.getDate() + nights);
        const fmt = (d) => d.toISOString().split("T")[0];

        try {
            await this.orm.write("hotel.reservation", [resId], {
                room_id: roomId,
                checkin_date: fmt(newCheckin),
                checkout_date: fmt(newCheckout),
            });
            await this.loadData();
        } catch (e) {
            console.error("Drag-drop update failed:", e);
        }
    }

    formatCurrency(value) {
        if (!value) return "0";
        return new Intl.NumberFormat("vi-VN").format(Math.round(value));
    }
}

registry.category("actions").add("hotel_reception_dashboard", ReceptionDashboard);
