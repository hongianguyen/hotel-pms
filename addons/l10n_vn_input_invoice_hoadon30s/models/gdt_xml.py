# -*- coding: utf-8 -*-
"""Parser for the regulated Vietnamese e-invoice XML (Decree 123/2020, TT78).

The provider also hands back a JSON rendition of each invoice, but its shape
is undocumented; the XML is the format the General Department of Taxation
mandates, so that is what we parse. The tag map below is the single place to
correct if a real payload disagrees with the spec.

Document skeleton::

    HDon                          (sometimes wrapped in TDiep/DLieu)
      DLHDon
        TTChung                   general info: form, serial, number, date
        NDHDon                    invoice content
          NBan                    seller
          NMua                    buyer
          DSHHDVu / HHDVu*        line items
          TToan                   totals
      MCCQT                       tax authority code
"""
import base64
import logging
from xml.etree import ElementTree

_logger = logging.getLogger(__name__)

# ── Tag map ──────────────────────────────────────────────────────────────
# Local element names, matched namespace-insensitively.
TAGS = {
    # General info (TTChung)
    'form_no': 'KHMSHDon',        # mẫu số hoá đơn        -> category
    'serial': 'KHHDon',           # ký hiệu hoá đơn
    'number': 'SHDon',            # số hoá đơn
    'date': 'NLap',               # ngày lập
    'currency': 'DVTTe',          # đơn vị tiền tệ
    'exchange_rate': 'TGia',      # tỷ giá
    'payment_method': 'HTTToan',  # hình thức thanh toán
    'invoice_type': 'THDon',      # tên hoá đơn
    # Parties
    'seller': 'NBan',
    'buyer': 'NMua',
    'party_name': 'Ten',
    'party_tax_code': 'MST',
    'party_address': 'DChi',
    'party_phone': 'SDThoai',
    'party_email': 'DCTDTu',
    'party_bank_account': 'STKNHang',
    # Lines
    'line_list': 'DSHHDVu',
    'line': 'HHDVu',
    'line_nature': 'TChat',       # 1 normal, 2 promotion, 3 discount, 4 note
    'line_seq': 'STT',
    'line_code': 'MHHDVu',
    'line_name': 'THHDVu',
    'line_uom': 'DVTinh',
    'line_qty': 'SLuong',
    'line_price': 'DGia',
    'line_subtotal': 'ThTien',
    'line_tax_rate': 'TSuat',
    'line_tax_amount': 'TThue',
    # Totals (TToan)
    'totals': 'TToan',
    'total_untaxed': 'TgTCThue',
    'total_tax': 'TgTThue',
    'total_amount': 'TgTTTBSo',
    # Trade-discount total. Real TT78 2.1.0 payloads write TTCKTMai; the
    # spec's TgTCKTMai is accepted too — both are tried, in that order.
    'total_discount': 'TTCKTMai',
    'total_discount_alt': 'TgTCKTMai',
    # Tax authority code
    'code_cqt': 'MCCQT',
}

# TChat: only nature 1 (normal goods/services) and 2 (promotional) carry a
# billable amount. 3 is a discount line, 4 is a free-text note.
LINE_NATURE_NORMAL = '1'
LINE_NATURE_PROMOTION = '2'
LINE_NATURE_DISCOUNT = '3'
LINE_NATURE_NOTE = '4'


def _local(tag):
    """Strip any XML namespace from an element tag."""
    return tag.rsplit('}', 1)[-1]


def _find(node, name):
    """First descendant (or self) with local tag `name`, or None."""
    if node is None:
        return None
    if _local(node.tag) == name:
        return node
    for child in node.iter():
        if _local(child.tag) == name:
            return child
    return None


def _find_all(node, name):
    if node is None:
        return []
    return [c for c in node.iter() if _local(c.tag) == name]


def _text(node, name, default=''):
    found = _find(node, name)
    if found is None or found.text is None:
        return default
    return found.text.strip()


def _to_float(value):
    """Parse a number that may use either 1,234.56 or 1.234,56 grouping."""
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    text = text.replace(' ', '')
    if ',' in text and '.' in text:
        # Whichever separator comes last is the decimal point.
        if text.rfind(',') > text.rfind('.'):
            text = text.replace('.', '').replace(',', '.')
        else:
            text = text.replace(',', '')
    elif ',' in text:
        # A lone comma: thousands grouping if every group after it is exactly
        # three digits (1,234,567), otherwise a decimal separator (1,5).
        groups = text.split(',')
        if all(len(g) == 3 and g.isdigit() for g in groups[1:]):
            text = text.replace(',', '')
        else:
            text = text.replace(',', '.')
    try:
        return float(text)
    except ValueError:
        _logger.warning('Could not parse number from e-invoice XML: %r', value)
        return 0.0


def parse_tax_rate(value):
    """Map a TSuat value to a percentage.

    Returns (percent, is_taxable). Vietnamese invoices use text markers for
    the non-numeric cases: KCT (không chịu thuế — not subject to VAT),
    KKKNT (không kê khai nộp thuế), and \\ or KHAC for "other".
    """
    text = (value or '').strip().upper().replace('%', '').strip()
    if not text or text in ('KCT', 'KKKNT', '\\', '-', 'KHAC', 'KHÁC'):
        return 0.0, False
    try:
        return float(text.replace(',', '.')), True
    except ValueError:
        return 0.0, False


def _parse_party(node):
    if node is None:
        return {}
    return {
        'name': _text(node, TAGS['party_name']),
        'tax_code': _text(node, TAGS['party_tax_code']),
        'address': _text(node, TAGS['party_address']),
        'phone': _text(node, TAGS['party_phone']),
        'email': _text(node, TAGS['party_email']),
        'bank_account': _text(node, TAGS['party_bank_account']),
    }


def _parse_line(node):
    rate_text = _text(node, TAGS['line_tax_rate'])
    percent, taxable = parse_tax_rate(rate_text)
    return {
        'nature': _text(node, TAGS['line_nature'], LINE_NATURE_NORMAL),
        'sequence': _to_float(_text(node, TAGS['line_seq'], '0')),
        'code': _text(node, TAGS['line_code']),
        'name': _text(node, TAGS['line_name']),
        'uom': _text(node, TAGS['line_uom']),
        'quantity': _to_float(_text(node, TAGS['line_qty'])),
        'price_unit': _to_float(_text(node, TAGS['line_price'])),
        'subtotal': _to_float(_text(node, TAGS['line_subtotal'])),
        'tax_rate_text': rate_text,
        'tax_rate': percent,
        'taxable': taxable,
        'tax_amount': _to_float(_text(node, TAGS['line_tax_amount'])),
    }


def parse_invoice_xml(xml_b64):
    """Parse a base64-encoded GDT invoice XML into a plain dict.

    Raises ValueError when the payload is not decodable XML — the caller
    records that against the invoice rather than losing the row.
    """
    try:
        raw = base64.b64decode(xml_b64)
    except Exception as exc:
        raise ValueError('Invoice XML is not valid base64: %s' % exc) from exc
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise ValueError('Invoice XML is not well-formed: %s' % exc) from exc

    # The payload may be a bare <HDon> or a full <TDiep> transport envelope;
    # anchoring on DLHDon/NDHDon finds the content either way.
    content = _find(root, 'NDHDon') or root
    general = _find(root, 'TTChung') or root
    totals = _find(content, TAGS['totals'])

    line_list = _find(content, TAGS['line_list'])
    lines = [_parse_line(n) for n in _find_all(line_list, TAGS['line'])] \
        if line_list is not None else []

    number_text = _text(general, TAGS['number'])
    return {
        'form_no': _text(general, TAGS['form_no']),
        'serial': _text(general, TAGS['serial']),
        'number': number_text,
        'date': _text(general, TAGS['date']),
        'currency': _text(general, TAGS['currency']) or 'VND',
        'exchange_rate': _to_float(_text(general, TAGS['exchange_rate'], '1'))
                         or 1.0,
        'payment_method': _text(general, TAGS['payment_method']),
        'invoice_type': _text(general, TAGS['invoice_type']),
        'code_cqt': _text(root, TAGS['code_cqt']),
        'seller': _parse_party(_find(content, TAGS['seller'])),
        'buyer': _parse_party(_find(content, TAGS['buyer'])),
        'lines': lines,
        'total_untaxed': _to_float(_text(totals, TAGS['total_untaxed'])),
        'total_tax': _to_float(_text(totals, TAGS['total_tax'])),
        'total_amount': _to_float(_text(totals, TAGS['total_amount'])),
        'total_discount': _to_float(
            _text(totals, TAGS['total_discount'])
            or _text(totals, TAGS['total_discount_alt'])),
    }
