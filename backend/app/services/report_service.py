# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
"""In-memory, local-only PDF net-worth reports."""
from __future__ import annotations

import base64
import binascii
from datetime import datetime
from io import BytesIO
from typing import Optional

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from backend.app.services.asset_service import list_liabilities, list_private_equity_assets, list_real_estate_assets, list_static_accounts
from backend.app.services.models import ReportBranding, ReportBrandingUpdate, ReportRequest
from backend.app.services.portfolio_service import dashboard, list_positions
from backend.app.services.insight_service import insights

DEFAULT_TITLE = "Portfolio Analyser Net-Worth Report"
MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_LOGO_DIMENSION = 4000
PAGE_W, PAGE_H = A4
MARGIN = 42


def _optional(value: Optional[str]) -> Optional[str]:
    return value.strip() or None if value else None


def _decode_logo(encoded: str) -> tuple[bytes, str]:
    try:
        # FileReader data URLs are accepted as well as the compact raw base64 form.
        raw_value = encoded.split(",", 1)[1] if encoded.startswith("data:") and "," in encoded else encoded
        raw = base64.b64decode(raw_value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Logo must be valid base64 PNG or JPEG image data.") from exc
    if not raw or len(raw) > MAX_LOGO_BYTES:
        raise ValueError("Logo must be no larger than 2 MB.")
    try:
        with Image.open(BytesIO(raw)) as image:
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            width, height = image.size
            image_format = image.format
    except Exception as exc:
        raise ValueError("Logo must be a valid PNG or JPEG image.") from exc
    if image_format not in {"PNG", "JPEG"}:
        raise ValueError("Logo must be a PNG or JPEG image.")
    if not width or not height or width > MAX_LOGO_DIMENSION or height > MAX_LOGO_DIMENSION:
        raise ValueError("Logo dimensions must be between 1 and 4000 pixels.")
    return raw, "image/png" if image_format == "PNG" else "image/jpeg"


def get_branding(conn) -> ReportBranding:
    row = conn.execute("SELECT title, subtitle, footer, logo_data FROM report_branding WHERE id=1").fetchone()
    if not row:
        return ReportBranding(title=DEFAULT_TITLE)
    return ReportBranding(title=row["title"], subtitle=row["subtitle"], footer=row["footer"], has_logo=bool(row["logo_data"]))


def save_branding(conn, payload: ReportBrandingUpdate) -> ReportBranding:
    title = payload.title.strip()
    if not title:
        raise ValueError("Report title is required.")
    logo_data = logo_mime = None
    if payload.logo_data_base64:
        logo_data, logo_mime = _decode_logo(payload.logo_data_base64)
    current = conn.execute("SELECT logo_data, logo_mime_type FROM report_branding WHERE id=1").fetchone()
    if not logo_data and not payload.remove_logo and current:
        logo_data, logo_mime = current["logo_data"], current["logo_mime_type"]
    conn.execute("""INSERT INTO report_branding(id, title, subtitle, footer, logo_data, logo_mime_type, updated_at)
        VALUES(1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET title=excluded.title, subtitle=excluded.subtitle, footer=excluded.footer,
          logo_data=excluded.logo_data, logo_mime_type=excluded.logo_mime_type, updated_at=CURRENT_TIMESTAMP""",
        (title, _optional(payload.subtitle), _optional(payload.footer), logo_data, logo_mime))
    return get_branding(conn)


def _effective_branding(conn, payload: ReportRequest):
    saved = conn.execute("SELECT logo_data FROM report_branding WHERE id=1").fetchone()
    logo = saved["logo_data"] if saved and not payload.remove_logo else None
    if payload.logo_data_base64:
        logo, _ = _decode_logo(payload.logo_data_base64)
    title = payload.title.strip()
    if not title:
        raise ValueError("Report title is required.")
    return title, _optional(payload.subtitle), _optional(payload.footer), logo


def _money(value: float, currency: str) -> str:
    symbol = {"USD": "$", "INR": "₹", "GBP": "£", "EUR": "€"}.get(currency, f"{currency} ")
    return f"{symbol}{value:,.2f}"


def _pie(data, title: str) -> BytesIO | None:
    values = [point.value for point in data if point.value > 0]
    labels = [point.label for point in data if point.value > 0]
    if not values:
        return None
    # Import only when rendering, retaining a lightweight API process until reports are used.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(3.2, 2.25), dpi=130)
    ax.pie(values, labels=labels, autopct=lambda p: f"{p:.0f}%" if p >= 5 else "", textprops={"fontsize": 7}, startangle=90)
    ax.set_title(title, fontsize=10, fontweight="bold")
    fig.tight_layout()
    output = BytesIO(); fig.savefig(output, format="png", transparent=True); plt.close(fig); output.seek(0)
    return output


def _footer(pdf: canvas.Canvas, page: int, currency: str, footer: Optional[str], as_of: str) -> None:
    pdf.setStrokeColor(colors.HexColor("#d1d5db")); pdf.line(MARGIN, 31, PAGE_W - MARGIN, 31)
    pdf.setFillColor(colors.HexColor("#4b5563")); pdf.setFont("Helvetica", 7.5)
    text = f"Holdings as of {as_of} • Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} • Display currency: {currency} • Page {page}"
    pdf.drawString(MARGIN, 19, text)
    if footer:
        pdf.drawRightString(PAGE_W - MARGIN, 19, footer[:150])


def _header(pdf: canvas.Canvas, title: str, subtitle: Optional[str], logo: bytes | None) -> float:
    y = PAGE_H - MARGIN
    if logo:
        try:
            image = ImageReader(BytesIO(logo)); width, height = image.getSize(); scale = min(54 / width, 34 / height)
            pdf.drawImage(image, MARGIN, y - height * scale + 2, width=width * scale, height=height * scale, mask="auto")
            title_x = MARGIN + 64
        except Exception:
            title_x = MARGIN
    else:
        title_x = MARGIN
    pdf.setFillColor(colors.HexColor("#102a43")); pdf.setFont("Helvetica-Bold", 17); pdf.drawString(title_x, y, title[:160])
    if subtitle:
        pdf.setFillColor(colors.HexColor("#52606d")); pdf.setFont("Helvetica", 9.5); pdf.drawString(title_x, y - 15, subtitle[:240])
    pdf.setStrokeColor(colors.HexColor("#2563eb")); pdf.setLineWidth(1.3); pdf.line(MARGIN, y - 25, PAGE_W - MARGIN, y - 25)
    return y - 42


def _section(pdf, title: str, y: float) -> float:
    pdf.setFillColor(colors.HexColor("#102a43")); pdf.setFont("Helvetica-Bold", 11); pdf.drawString(MARGIN, y, title)
    return y - 15


def _report_metadata(pdf: canvas.Canvas, y: float, as_of: str, currency: str) -> float:
    """Show the reporting basis prominently on the first summary page."""
    pdf.setFillColor(colors.HexColor("#52606d"))
    pdf.setFont("Helvetica", 8.5)
    pdf.drawString(MARGIN, y, f"Holdings as of: {as_of}")
    pdf.drawRightString(PAGE_W - MARGIN, y, f"Report currency: {currency}")
    return y - 20


def _component_rows(analytics) -> list[list[str]]:
    amounts = {point.label: point.value for point in analytics.net_worth_allocation}
    categories = [
        ("Brokerage", analytics.brokerage_value),
        ("Bank Account", amounts.get("Bank Account", 0)),
        ("Retirement Account", amounts.get("Retirement Account", 0)),
        ("Other", amounts.get("Other", 0)),
        ("Real Estate", analytics.real_estate_value),
        ("Private Equity", analytics.private_equity_value),
    ]
    return [[label, _money(value, analytics.display_currency)] for label, value in categories]


def _liability_rows(conn, currency: str) -> list[list[str]]:
    totals: dict[str, float] = {}
    for liability in list_liabilities(conn):
        label = liability.custom_type if liability.liability_type == "Other" and liability.custom_type else liability.liability_type
        totals[label] = totals.get(label, 0) + liability.outstanding_balance_display
    if len(totals) > 8:
        ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        retained, remainder = ranked[:7], ranked[7:]
        totals = dict(retained)
        totals["Other liability types"] = sum(value for _, value in remainder)
    return [[label, _money(value, currency)] for label, value in sorted(totals.items())] or [["No liabilities", _money(0, currency)]]


def _compact_table(pdf: canvas.Canvas, x: float, y: float, width: float, title: str, rows: list[list[str]]) -> None:
    """Small fixed-height summary table for the one-page executive layout."""
    pdf.setFillColor(colors.HexColor("#102a43")); pdf.setFont("Helvetica-Bold", 9); pdf.drawString(x, y, title)
    y -= 12
    pdf.setFillColor(colors.HexColor("#e6f0ff")); pdf.rect(x, y - 11, width, 13, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#102a43")); pdf.setFont("Helvetica-Bold", 6.5)
    pdf.drawString(x + 3, y - 7, "Category / type"); pdf.drawRightString(x + width - 3, y - 7, "Value")
    for index, (label, value) in enumerate(rows[:8]):
        line_y = y - 14 - index * 11
        if index % 2 == 0:
            pdf.setFillColor(colors.HexColor("#f8fafc")); pdf.rect(x, line_y - 8, width, 11, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#1f2933")); pdf.setFont("Helvetica", 6.5)
        pdf.drawString(x + 3, line_y - 5, label[:28]); pdf.drawRightString(x + width - 3, line_y - 5, value)


def _assets_liabilities_bar(total_assets: float, total_liabilities: float, currency: str) -> BytesIO:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.2, 1.05), dpi=130)
    labels, values = ["Gross assets", "Liabilities"], [total_assets, total_liabilities]
    bars = ax.bar(labels, values, color=["#2563eb", "#dc2626"], width=0.48)
    ax.set_title(f"Assets vs liabilities ({currency})", fontsize=9, fontweight="bold", pad=4)
    ax.tick_params(axis="both", labelsize=7); ax.spines[["top", "right", "left"]].set_visible(False); ax.tick_params(axis="y", left=False, labelleft=False)
    for bar, value in zip(bars, values): ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), _money(value, currency), ha="center", va="bottom", fontsize=7)
    fig.tight_layout(); output = BytesIO(); fig.savefig(output, format="png", transparent=True); plt.close(fig); output.seek(0)
    return output


def _table(pdf, headers: list[str], rows: list[list[str]], y: float, page: int, currency: str, footer: Optional[str], as_of: str, branding) -> tuple[float, int]:
    widths = [(PAGE_W - 2 * MARGIN) / len(headers)] * len(headers)
    def draw_head(at: float) -> float:
        pdf.setFillColor(colors.HexColor("#e6f0ff")); pdf.rect(MARGIN, at - 12, sum(widths), 15, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#102a43")); pdf.setFont("Helvetica-Bold", 7)
        x = MARGIN
        for h, w in zip(headers, widths): pdf.drawString(x + 3, at - 8, h[:28]); x += w
        return at - 17
    y = draw_head(y)
    for index, row in enumerate(rows):
        if y < 55:
            _footer(pdf, page, currency, footer, as_of); pdf.showPage(); page += 1; y = _header(pdf, branding[0], branding[1], branding[3]); y = _section(pdf, "Appendix (continued)", y); y = draw_head(y)
        if index % 2 == 0:
            pdf.setFillColor(colors.HexColor("#f8fafc")); pdf.rect(MARGIN, y - 10, sum(widths), 13, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#1f2933")); pdf.setFont("Helvetica", 7)
        x = MARGIN
        for item, w in zip(row, widths):
            pdf.drawString(x + 3, y - 7, str(item)[:30]); x += w
        y -= 13
    return y, page


def generate_report(conn, payload: ReportRequest) -> bytes:
    kind = payload.report_type.lower()
    if kind not in {"summary", "detail"}:
        raise ValueError("Report type must be Summary or Detail.")
    branding = _effective_branding(conn, payload)
    title, subtitle, footer, logo = branding
    analytics = dashboard(conn); liquidity = insights(conn, include_forecast=False).liquidity; currency = analytics.display_currency
    as_of = conn.execute("SELECT MAX(snapshot_date) FROM positions").fetchone()[0] or "no holdings snapshot"
    output = BytesIO(); pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1); page = 1
    y = _header(pdf, title, subtitle, logo)
    y = _report_metadata(pdf, y, as_of, currency)
    y = _section(pdf, "Executive summary", y)
    metrics = [("Gross assets", analytics.total_assets), ("Total liabilities", analytics.total_liabilities), ("Total net worth", analytics.total_net_worth), ("Brokerage", analytics.brokerage_value), ("Real estate", analytics.real_estate_value), ("Unrealized P/L", analytics.unrealized_gain_loss)]
    for index, (label, value) in enumerate(metrics):
        x = MARGIN + (index % 2) * ((PAGE_W - 2 * MARGIN) / 2); row_y = y - (index // 2) * 25
        pdf.setFillColor(colors.HexColor("#52606d")); pdf.setFont("Helvetica", 8); pdf.drawString(x, row_y, label)
        pdf.setFillColor(colors.HexColor("#15803d") if label == "Unrealized P/L" and value >= 0 else colors.HexColor("#b91c1c") if label == "Unrealized P/L" else colors.HexColor("#102a43")); pdf.setFont("Helvetica-Bold", 11); pdf.drawString(x, row_y - 12, _money(value, currency))
    y -= 88
    _compact_table(pdf, MARGIN, y, 246, "Assets", _component_rows(analytics))
    _compact_table(pdf, PAGE_W - MARGIN - 246, y, 246, "Liabilities", _liability_rows(conn, currency))
    y -= 116
    pdf.drawImage(ImageReader(_assets_liabilities_bar(analytics.total_assets, analytics.total_liabilities, currency)), MARGIN, y - 82, width=PAGE_W - 2 * MARGIN, height=82, mask="auto")
    y -= 92
    asset_chart = _pie(analytics.asset_allocation, "Asset allocation")
    liquidity_chart = _pie(liquidity, "Liquidity composition")
    if asset_chart: pdf.drawImage(ImageReader(asset_chart), MARGIN, y - 145, width=220, height=145, mask="auto")
    if liquidity_chart: pdf.drawImage(ImageReader(liquidity_chart), PAGE_W - MARGIN - 220, y - 145, width=220, height=145, mask="auto")
    if kind == "summary":
        _footer(pdf, page, currency, footer, as_of); pdf.save(); return output.getvalue()
    _footer(pdf, page, currency, footer, as_of); pdf.showPage(); page += 1
    y = _header(pdf, title, subtitle, logo); y = _section(pdf, "Holdings appendix", y)
    positions = list_positions(conn)
    holding_rows = [[p.broker_name, p.account_mask or "—", f"{p.security_name} ({p.symbol or '—'})", _money(p.total_fmv_display or 0, currency)] for p in positions]
    y, page = _table(pdf, ["Broker", "Masked account", "Security", "Market value"], holding_rows or [["No holdings", "", "", ""]], y, page, currency, footer, as_of, branding)
    for label, headers, rows in [
        ("Bank, retirement & other accounts", ["Category", "Institution", "Masked account", "Value"], [[a.category, a.entity_name, a.account_mask or "—", _money(a.amount_display, currency)] for a in list_static_accounts(conn)]),
        ("Real estate", ["Property", "Entity", "Purchase value", "Current value"], [[a.property_info, a.entity_name or "—", _money(a.purchase_value_display, currency), _money(a.current_value_display, currency)] for a in list_real_estate_assets(conn)]),
        ("Private equity", ["Company", "Stage / class", "Investment value", "Current value"], [[a.company_name, f"{a.stage} / {a.share_class}", _money(a.purchase_value_display, currency), _money(a.current_value_display, currency)] for a in list_private_equity_assets(conn)]),
        ("Liabilities", ["Entity", "Type", "Masked reference", "Outstanding balance", "Notes"], [[a.entity_name, a.custom_type or a.liability_type, a.account_reference_mask or "—", _money(a.outstanding_balance_display, currency), a.notes or "—"] for a in list_liabilities(conn)]),
    ]:
        if y < 110:
            _footer(pdf, page, currency, footer, as_of); pdf.showPage(); page += 1; y = _header(pdf, title, subtitle, logo)
        y = _section(pdf, label, y)
        y, page = _table(pdf, headers, rows or [["No assets recorded", "", "", ""]], y, page, currency, footer, as_of, branding)
        y -= 13
    _footer(pdf, page, currency, footer, as_of); pdf.save(); return output.getvalue()
