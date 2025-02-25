##############################################################################
#
#    Copyright (C) 2018 Compassion CH (http://www.compassion.ch)
#    Releasing children from poverty in Jesus' name
#    @author: Emanuel Cino
#
#    The licence is in the file __manifest__.py
#
##############################################################################
from datetime import datetime

import werkzeug
from dateutil.relativedelta import relativedelta

from odoo import http, _, fields
from odoo.addons.http_routing.models.ir_http import slug
from odoo.addons.website.models.ir_http import sitemap_qs2dom
from odoo.http import request

from odoo.addons.cms_form.controllers.main import FormControllerMixin
from odoo.addons.cms_form_compassion.controllers.payment_controller import (
    PaymentFormController,
)


class EventsController(PaymentFormController, FormControllerMixin):
    def sitemap_events(env, rule, qs):
        today = fields.Date.to_string(datetime.today())
        events = env["crm.event.compassion"]
        dom = sitemap_qs2dom(qs, '/events', events._rec_name)
        dom += request.website.website_domain()
        dom += [("website_published", "=", True), ("end_date", ">=", today)]
        for reg in events.search(dom):
            loc = '/event/%s' % slug(reg)
            if not qs or qs.lower() in loc:
                yield {'loc': loc}

    def sitemap_participants(env, rule, qs):
        registrations = env["event.registration"]
        dom = sitemap_qs2dom(qs, '/event', registrations._rec_name)
        dom += request.website.website_domain()
        dom += [("website_published", "=", True)]
        for reg in registrations.search(dom):
            loc = '/event/%s/%s' % (slug(reg.compassion_event_id), slug(reg))
            if not qs or qs.lower() in loc:
                yield {'loc': loc}

    @http.route("/events/", auth="public", website=True, sitemap=False)
    def list(self, **kwargs):
        today = fields.Date.to_string(datetime.today())
        # Events that are set to finish after today
        started_events = request.env["crm.event.compassion"].search([
            ("website_published", "=", True), ("end_date", ">=", today),
        ])
        if len(started_events) == 1:
            return request.redirect("/event/" + str(started_events.id))
        return request.render(
            "website_event_compassion.list", {"events": started_events}
        )

    ###################################################
    # Methods for the event page and event registration
    ###################################################
    @http.route(
        '/event/<model("crm.event.compassion"):event>/', auth="public", website=True,
        sitemap=sitemap_events
    )
    def event_page(self, event, **kwargs):
        if not event.is_published and request.env.user.share:
            return request.redirect("/events")

        if not event.can_access_from_current_website():
            raise werkzeug.exceptions.NotFound()

        values = self.get_event_page_values(event, **kwargs)
        registration_form = values["form"]
        if registration_form.form_success:
            # The user submitted a registration, redirect to confirmation
            result = werkzeug.utils.redirect(
                registration_form.form_next_url(), code=303
            )
        else:
            # Check if registration was already present
            errors = registration_form.form_render_values.get("errors")
            if errors and errors.get("_integrity"):
                request.env.cr.rollback()
                # Replace error message with more friendly text.
                request.website.get_status_message()
                request.website.add_status_message(
                    _("You are already registered to this trip."),
                    type_="danger",
                    title=_("Error"),
                )
            # Display the Event page
            result = request.render(values.pop("website_template"), values)
        if event.event_type_id.sudo().travel_features:
            # Travel events are full not called by AJAX popup form
            return result
        return result

    @http.route(
        '/event/<model("crm.event.compassion"):event>/faq', auth="public", website=True,
        sitemap=False
    )
    def event_faq(self, event, **kwargs):
        if not event.is_published and not request.env.user.has_group(
                "website.group_website_designer"):
            return request.redirect("/events")

        return request.render("website_event_compassion.event_faq", {"event": event})

    @http.route(
        '/event/<model("event.event"):event>/registration/'
        '<int:registration_id>/success',
        auth="public",
        website=True, sitemap=False
    )
    def registration_success(self, event, registration_id, **kwargs):
        limit_date = datetime.now() - relativedelta(days=1)
        registration = request.env["event.registration"].sudo().browse(registration_id)
        if not registration.exists() or registration.create_date < limit_date:
            return request.redirect("/events")

        values = {"event": event, "attendees": registration}
        return request.render(
            "website_event_compassion.event_registration_successful", values
        )

    @http.route(
        '/event/<model("crm.event.compassion"):event>/confirmation/',
        auth="public",
        website=True, sitemap=False
    )
    def confirmation_page(self, event, **kwargs):
        if not event.is_published:
            return request.redirect("/events")

        values = {
            "confirmation_title": kwargs.get("title"),
            "confirmation_message": kwargs.get("message"),
            "event": event,
        }
        return request.render(
            "website_event_compassion.event_confirmation_page", values
        )

    def get_event_page_values(self, event, **kwargs):
        """
        Processes the registration form and gets the values used by the website to
        render the event page.
        :param event: crm.event.compassion record to render
        :param kwargs: request arguments
        :return: dict: values for the event website template
                       (must contain event, start_date, end_date, form,
                        main_object and website_template values)
        """
        values = kwargs.copy()
        # This allows the translation to still work on the page
        values.pop("edit_translations", False)
        values.update(
            {
                "event": event,
                "start_date": event.get_date("start_date", "date_full"),
                "end_date": event.get_date("end_date", "date_full"),
                "additional_title": _("- Registration"),
            }
        )
        # Travel display only registration form, others do have a page.
        template = "website_event_compassion."
        if event.event_type_id.sudo().travel_features:
            values["form_model_key"] = "cms.form.group.visit.registration"
            template += "event_full_page_form"
        else:
            template += "event_page"
        registration_form = self.get_form("event.registration", **values)
        registration_form.form_process()
        values.update(
            {
                "form": registration_form,
                "main_object": event,
                "website_template": template,
                "event_step": 1,
            }
        )
        return values

    ###################################################
    # Methods for the participant page and the donation
    ###################################################
    @http.route(
        [
            "/event/<model('crm.event.compassion'):event>/<reg_string>-<int:reg_id>",
            "/event/<model('crm.event.compassion'):event>/<int:reg_id>",
        ],
        auth="public", website=True, sitemap=sitemap_participants
    )
    def participant_details(self, event, reg_id, **kwargs):
        """
        :param event: the event record
        :param reg_id: the registration record
        :return:the rendered page
        """
        if not event.is_published:
            return request.redirect("/events")

        reg_obj = request.env["event.registration"].sudo()
        registration = reg_obj.browse(reg_id).exists().filtered("website_published")
        if not registration:
            return werkzeug.utils.redirect("/event/" + str(event.id), 301)
        kwargs["form_model_key"] = "cms.form.event.donation"
        values = self.get_participant_page_values(event, registration, **kwargs)
        donation_form = values["form"]
        if donation_form.form_success:
            # The user submitted a donation, redirect to confirmation
            result = werkzeug.utils.redirect(donation_form.form_next_url(), code=303)
        else:
            result = request.render(values["website_template"], values)
        return result

    def get_participant_page_values(self, event, registration, **kwargs):
        """
        Gets the values used by the website to render the participant page.
        :param event: crm.event.compassion record to render
        :param registration: event.registration record to render
        :param kwargs: request arguments
        :return: dict: values for the event website template
                       (must contain event, start_date, end_date, form,
                        main_object and website_template values)
        """
        values = kwargs.copy()
        # This allows the translation to still work on the page
        values.pop("edit_translations", False)
        values.update({
            "event": event, "registration": registration,
        })
        donation_form = self.get_form(False, **values)
        donation_form.form_process()
        values.update(
            {
                "form": donation_form,
                "main_object": registration,
                "website_template": "website_event_compassion.participant_page",
            }
        )
        return values

    ########################################
    # Methods for after donation redirection
    ########################################
    @http.route("/event/payment/validate/<int:invoice_id>",
                type="http", auth="public", website=True,
                sitemap=False)
    def donation_payment_validate(self, invoice_id=None, **kwargs):
        """ Method that should be called by the server when receiving an update
        for a transaction.
        """
        try:
            invoice = request.env["account.invoice"].browse(int(invoice_id)).sudo()
            invoice.exists().ensure_one()
            transaction = invoice.get_portal_last_transaction()
        except ValueError:
            transaction = request.env["payment.transaction"]

        invoice_lines = invoice.invoice_line_ids
        event = invoice_lines.mapped("event_id")

        if transaction.state != "done":
            return request.render(
                self.get_donation_failure_template(event), {"error_intro": ""}
            )

        ambassador = invoice_lines.mapped("user_id")
        registration = event.registration_ids.filtered(
            lambda r: r.partner_id == ambassador
        )
        values = {"registration": registration, "event": event, "error_intro": ""}
        success_template = self.get_donation_success_template(event)
        return request.render(success_template, values)

    @http.route(
        "/event/payment/gpv_payment_validate/<int:invoice_id>", type="http",
        auth="public", website=True, sitemap=False
    )
    def down_payment_validate(self, invoice_id=None, **post):
        """ Method that should be called by the server when receiving an update
        for a transaction.
        """
        failure_template = "website_event_compassion.donation_failure"
        error_intro = _(
            "Thank you for your efforts in the Compassion trip registration process."
        )
        try:
            invoice = request.env["account.invoice"].browse(int(invoice_id)).sudo()
            invoice.exists().ensure_one()
            tx = invoice.get_portal_last_transaction()
        except ValueError:
            tx = request.env["payment.transaction"]

        if tx.state != "done":
            return request.render(failure_template, {"error_intro": error_intro})

        invoice_lines = invoice.invoice_line_ids
        event = invoice_lines.mapped("event_id")
        registration = tx.registration_id
        post.update(
            {
                "attendees": registration,
                "event": event,
                "confirmation_title": _("We are glad to confirm your registration!"),
                "confirmation_message": _(
                    "Thank you for your efforts in the Compassion trip "
                    "registration process."
                )
                + "<br/><br/>"
                + _(
                    "Your payment was successful and your are now a confirmed "
                    "participant of the trip. You will receive all the "
                    "documentation for the preparation of your trip by e-mail in "
                    "the coming weeks."
                ),
                "error_intro": error_intro,
            }
        )
        template = "website_event_compassion.event_confirmation_page"
        if invoice == registration.group_visit_invoice_id:
            post["confirmation_message"] = _(
                "Congratulations! Everything is ready for this beautiful "
                "trip to happen. You will receive all the practical "
                "information about the trip preparation a few weeks before "
                "the departure. Until then, don't hesitate to contact us if "
                "you have any question."
            )
        return request.render(template, post)

    def get_donation_success_template(self, event):
        """
        Gets the website templates for donation confirmation
        :param event: crm.event.compassion record
        :return: xml_id of website template
        """
        return "website_event_compassion.donation_successful"
