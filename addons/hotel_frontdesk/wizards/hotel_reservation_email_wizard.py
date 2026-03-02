# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HotelReservationEmailWizard(models.TransientModel):
    _name = 'hotel.reservation.email.wizard'
    _description = 'Send Reservation Confirmation Email'

    reservation_id = fields.Many2one('hotel.reservation', required=True, readonly=True)
    email_to = fields.Char(_('To'), required=True)
    subject = fields.Char(_('Subject'), required=True)
    body_html = fields.Html(_('Body'), required=True, sanitize=False)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        reservation_id = self.env.context.get('default_reservation_id')
        if reservation_id:
            reservation = self.env['hotel.reservation'].browse(reservation_id)
            template = self.env.ref(
                'hotel_frontdesk.mail_template_reservation_confirmation',
                raise_if_not_found=False,
            )
            if template:
                rendered = template._render_field(
                    'subject', reservation.ids,
                    compute_lang=True,
                )[reservation.id]
                rendered_body = template._render_field(
                    'body_html', reservation.ids,
                    compute_lang=True,
                )[reservation.id]
                res['subject'] = rendered
                res['body_html'] = rendered_body
            else:
                res['subject'] = _('Reservation Confirmation - %s') % reservation.reservation_number
                res['body_html'] = _('<p>Dear %s,</p><p>Your reservation %s has been confirmed.</p>') % (
                    reservation.guest_id.name, reservation.reservation_number
                )
            res['email_to'] = reservation.guest_id.email or ''
        return res

    def action_send(self):
        self.ensure_one()
        if not self.email_to:
            raise UserError(_('No recipient email address provided.'))

        self.env['mail.mail'].sudo().create({
            'subject': self.subject,
            'email_to': self.email_to,
            'body_html': self.body_html,
            'model': 'hotel.reservation',
            'res_id': self.reservation_id.id,
            'auto_delete': True,
        }).send()

        self.reservation_id.message_post(
            body=_('Confirmation email sent to %s.') % self.email_to,
            message_type='notification',
        )
        return {'type': 'ir.actions.act_window_close'}
