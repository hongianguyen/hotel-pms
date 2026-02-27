/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, useState, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class AdminDashboard extends Component {
    static template = "hotel_reporting.AdminDashboard";

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            kpis: {},
            revenueData: [],
            occupancyData: [],
            loading: true,
        });
        this.revenueChartRef = useRef("revenueChart");
        this.occupancyChartRef = useRef("occupancyChart");

        onWillStart(async () => {
            await this.loadData();
        });

        onMounted(() => {
            this.renderCharts();
        });
    }

    async loadData() {
        this.state.loading = true;
        try {
            const [kpis, revenueData, occupancyData] = await Promise.all([
                this.orm.call("hotel.dashboard", "get_admin_kpis", []),
                this.orm.call("hotel.dashboard", "get_revenue_chart_data", []),
                this.orm.call("hotel.dashboard", "get_occupancy_trend", []),
            ]);
            this.state.kpis = kpis;
            this.state.revenueData = revenueData;
            this.state.occupancyData = occupancyData;
        } catch (e) {
            console.error("Failed to load admin dashboard:", e);
        }
        this.state.loading = false;
    }

    async onRefresh() {
        await this.loadData();
        this.renderCharts();
    }

    renderCharts() {
        // Revenue chart rendering handled by template (CSS bar chart)
    }

    getMaxRevenue() {
        if (!this.state.revenueData.length) return 1;
        return Math.max(
            ...this.state.revenueData.map((d) => d.room + d.fnb + d.service),
            1
        );
    }

    getBarHeight(item) {
        const total = item.room + item.fnb + item.service;
        const max = this.getMaxRevenue();
        return Math.max((total / max) * 180, 2);
    }

    getMaxOccupancy() {
        if (!this.state.occupancyData.length) return 100;
        return Math.max(...this.state.occupancyData.map((d) => d.occupancy), 1);
    }

    getOccupancyBarHeight(item) {
        const max = this.getMaxOccupancy();
        return Math.max((item.occupancy / max) * 180, 2);
    }

    getPieSlices() {
        const kpis = this.state.kpis;
        const total = (kpis.room_revenue || 0) + (kpis.fnb_revenue || 0) + (kpis.service_revenue || 0);
        if (!total) return [];

        const roomPct = ((kpis.room_revenue || 0) / total) * 100;
        const fnbPct = ((kpis.fnb_revenue || 0) / total) * 100;
        const servicePct = ((kpis.service_revenue || 0) / total) * 100;

        return [
            { label: 'Room', pct: roomPct, color: '#2563EB', value: kpis.room_revenue },
            { label: 'F&B', pct: fnbPct, color: '#22C55E', value: kpis.fnb_revenue },
            { label: 'Service', pct: servicePct, color: '#F97316', value: kpis.service_revenue },
        ];
    }

    formatCurrency(value) {
        if (!value) return "0";
        return new Intl.NumberFormat("vi-VN").format(Math.round(value));
    }
}

registry.category("actions").add("hotel_admin_dashboard", AdminDashboard);
