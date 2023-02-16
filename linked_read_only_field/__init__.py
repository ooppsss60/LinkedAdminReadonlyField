import json
from django.contrib.admin.helpers import AdminField
from django.contrib.admin.utils import (
    display_for_field, help_text_for_field,
    label_for_field, lookup_field,
)
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import ManyToManyRel, ManyToOneRel
from django.template.defaultfilters import capfirst, linebreaksbr
from django.urls import reverse
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext, gettext_lazy as _
from django.contrib.admin.options import ModelAdmin, TO_FIELD_VAR, IS_POPUP_VAR
from django.contrib.admin import helpers
from django.contrib.admin.exceptions import DisallowedModelAdminToField
from django.contrib.admin.utils import flatten_fieldsets, unquote
from django.core.exceptions import PermissionDenied
from django.forms.formsets import all_valid
from django.utils.text import capfirst
from django.utils.translation import gettext as _


__all__ = ['LinkedModelAdmin']


class LinkedAdminReadonlyField(helpers.AdminReadonlyField):
    def contents(self):
        from django.contrib.admin.templatetags.admin_list import _boolean_icon
        field, obj, model_admin = self.field['field'], self.form.instance, self.model_admin
        try:
            f, attr, value = lookup_field(field, obj, model_admin)
        except (AttributeError, ValueError, ObjectDoesNotExist):
            result_repr = self.empty_value_display
        else:
            if field in self.form.fields:
                widget = self.form[field].field.widget
                # This isn't elegant but suffices for contrib.auth's
                # ReadOnlyPasswordHashWidget.
                if getattr(widget, 'read_only', False):
                    return widget.render(field, value)
            if f is None:
                if getattr(attr, 'boolean', False):
                    result_repr = _boolean_icon(value)
                else:
                    if hasattr(value, "__html__"):
                        result_repr = value
                    else:
                        result_repr = linebreaksbr(value)
            else:
                if isinstance(f.remote_field, ManyToManyRel) and value is not None:
                    result_repr = ", ".join(map(str, value.all()))
                elif (
                    isinstance(f.remote_field, ManyToOneRel) and
                    value is not None and
                    type(value) in model_admin.admin_site._registry
                ):
                    rel_opts = value._meta
                    info = (rel_opts.app_label, rel_opts.model_name)
                    current_app = model_admin.admin_site.name
                    action = 'change'
                    change_url = reverse(
                        "admin:%s_%s_%s" % (info + (action,)),
                        current_app=current_app, args=(value.pk,)
                    )
                    text = display_for_field(value, f, self.empty_value_display)
                    result_repr = mark_safe(
                        f'<a href="{change_url}">{text}</a>'
                    )
                else:
                    result_repr = display_for_field(value, f, self.empty_value_display)
                result_repr = linebreaksbr(result_repr)
        return conditional_escape(result_repr)


class LinkedAdminForm(helpers.AdminForm):
    def __iter__(self):
        for name, options in self.fieldsets:
            yield LinkedFieldset(
                self.form, name,
                readonly_fields=self.readonly_fields,
                model_admin=self.model_admin,
                **options
            )


class LinkedFieldset(helpers.Fieldset):

    def __iter__(self):
        for field in self.fields:
            yield LinkedFieldline(self.form, field, self.readonly_fields, model_admin=self.model_admin)


class LinkedFieldline(helpers.Fieldline):
    def __iter__(self):
        for i, field in enumerate(self.fields):
            if field in self.readonly_fields:
                yield LinkedAdminReadonlyField(self.form, field, is_first=(i == 0), model_admin=self.model_admin)
            else:
                yield AdminField(self.form, field, is_first=(i == 0))


class LinkedInlineAdminFormSet(helpers.InlineAdminFormSet):
    def __iter__(self):
        if self.has_change_permission:
            readonly_fields_for_editing = self.readonly_fields
        else:
            readonly_fields_for_editing = self.readonly_fields + flatten_fieldsets(self.fieldsets)

        for form, original in zip(self.formset.initial_forms, self.formset.get_queryset()):
            view_on_site_url = self.opts.get_view_on_site_url(original)
            yield LinkedInlineAdminForm(
                self.formset, form, self.fieldsets, self.prepopulated_fields,
                original, readonly_fields_for_editing, model_admin=self.opts,
                view_on_site_url=view_on_site_url,
            )
        for form in self.formset.extra_forms:
            yield LinkedInlineAdminForm(
                self.formset, form, self.fieldsets, self.prepopulated_fields,
                None, self.readonly_fields, model_admin=self.opts,
            )
        if self.has_add_permission:
            yield LinkedInlineAdminForm(
                self.formset, self.formset.empty_form,
                self.fieldsets, self.prepopulated_fields, None,
                self.readonly_fields, model_admin=self.opts,
            )

    def fields(self):
        fk = getattr(self.formset, "fk", None)
        empty_form = self.formset.empty_form
        meta_labels = empty_form._meta.labels or {}
        meta_help_texts = empty_form._meta.help_texts or {}
        for i, field_name in enumerate(flatten_fieldsets(self.fieldsets)):
            if fk and fk.name == field_name:
                continue
            if not self.has_change_permission or field_name in self.readonly_fields:
                yield {
                    'name': field_name,
                    'label': meta_labels.get(field_name) or label_for_field(
                        field_name,
                        self.opts.model,
                        self.opts,
                        form=empty_form,
                    ),
                    'widget': {'is_hidden': False},
                    'required': False,
                    'help_text': meta_help_texts.get(field_name) or help_text_for_field(field_name, self.opts.model),
                }
            else:
                form_field = empty_form.fields[field_name]
                label = form_field.label
                if label is None:
                    label = label_for_field(field_name, self.opts.model, self.opts, form=empty_form)
                yield {
                    'name': field_name,
                    'label': label,
                    'widget': form_field.widget,
                    'required': form_field.required,
                    'help_text': form_field.help_text,
                }

    def inline_formset_data(self):
        verbose_name = self.opts.verbose_name
        return json.dumps({
            'name': '#%s' % self.formset.prefix,
            'options': {
                'prefix': self.formset.prefix,
                'addText': gettext('Add another %(verbose_name)s') % {
                    'verbose_name': capfirst(verbose_name),
                },
                'deleteText': gettext('Remove'),
            }
        })

    @property
    def forms(self):
        return self.formset.forms

    @property
    def non_form_errors(self):
        return self.formset.non_form_errors

    @property
    def media(self):
        media = self.opts.media + self.formset.media
        for fs in self:
            media = media + fs.media
        return media


class LinkedInlineAdminForm(helpers.InlineAdminForm):

    def __iter__(self):
        for name, options in self.fieldsets:
            yield LinkedInlineFieldset(
                self.formset, self.form, name, self.readonly_fields,
                model_admin=self.model_admin, **options
            )


class LinkedInlineFieldset(helpers.InlineFieldset):
    def __iter__(self):
        fk = getattr(self.formset, "fk", None)
        for field in self.fields:
            if not fk or fk.name != field:
                yield LinkedFieldline(self.form, field, self.readonly_fields, model_admin=self.model_admin)


class LinkedModelAdmin(ModelAdmin):
    def _changeform_view(self, request, object_id, form_url, extra_context):
        to_field = request.POST.get(TO_FIELD_VAR, request.GET.get(TO_FIELD_VAR))
        if to_field and not self.to_field_allowed(request, to_field):
            raise DisallowedModelAdminToField("The field %s cannot be referenced." % to_field)

        model = self.model
        opts = model._meta

        if request.method == 'POST' and '_saveasnew' in request.POST:
            object_id = None

        add = object_id is None

        if add:
            if not self.has_add_permission(request):
                raise PermissionDenied
            obj = None

        else:
            obj = self.get_object(request, unquote(object_id), to_field)

            if request.method == 'POST':
                if not self.has_change_permission(request, obj):
                    raise PermissionDenied
            else:
                if not self.has_view_or_change_permission(request, obj):
                    raise PermissionDenied

            if obj is None:
                return self._get_obj_does_not_exist_redirect(request, opts, object_id)

        fieldsets = self.get_fieldsets(request, obj)
        ModelForm = self.get_form(
            request, obj, change=not add, fields=flatten_fieldsets(fieldsets)
        )
        if request.method == 'POST':
            form = ModelForm(request.POST, request.FILES, instance=obj)
            form_validated = form.is_valid()
            if form_validated:
                new_object = self.save_form(request, form, change=not add)
            else:
                new_object = form.instance
            formsets, inline_instances = self._create_formsets(request, new_object, change=not add)
            if all_valid(formsets) and form_validated:
                self.save_model(request, new_object, form, not add)
                self.save_related(request, form, formsets, not add)
                change_message = self.construct_change_message(request, form, formsets, add)
                if add:
                    self.log_addition(request, new_object, change_message)
                    return self.response_add(request, new_object)
                else:
                    self.log_change(request, new_object, change_message)
                    return self.response_change(request, new_object)
            else:
                form_validated = False
        else:
            if add:
                initial = self.get_changeform_initial_data(request)
                form = ModelForm(initial=initial)
                formsets, inline_instances = self._create_formsets(request, form.instance, change=False)
            else:
                form = ModelForm(instance=obj)
                formsets, inline_instances = self._create_formsets(request, obj, change=True)

        if not add and not self.has_change_permission(request, obj):
            readonly_fields = flatten_fieldsets(fieldsets)
        else:
            readonly_fields = self.get_readonly_fields(request, obj)
        adminForm = LinkedAdminForm(
            form,
            list(fieldsets),
            # Clear prepopulated fields on a view-only form to avoid a crash.
            self.get_prepopulated_fields(request, obj) if add or self.has_change_permission(request, obj) else {},
            readonly_fields,
            model_admin=self)
        media = self.media + adminForm.media

        inline_formsets = self.get_inline_formsets(request, formsets, inline_instances, obj)
        for inline_formset in inline_formsets:
            media = media + inline_formset.media

        if add:
            title = _('Add %s')
        elif self.has_change_permission(request, obj):
            title = _('Change %s')
        else:
            title = _('View %s')
        context = {
            **self.admin_site.each_context(request),
            'title': title % opts.verbose_name,
            'adminform': adminForm,
            'object_id': object_id,
            'original': obj,
            'is_popup': IS_POPUP_VAR in request.POST or IS_POPUP_VAR in request.GET,
            'to_field': to_field,
            'media': media,
            'inline_admin_formsets': inline_formsets,
            'errors': helpers.AdminErrorList(form, formsets),
            'preserved_filters': self.get_preserved_filters(request),
        }

        # Hide the "Save" and "Save and continue" buttons if "Save as New" was
        # previously chosen to prevent the interface from getting confusing.
        if request.method == 'POST' and not form_validated and "_saveasnew" in request.POST:
            context['show_save'] = False
            context['show_save_and_continue'] = False
            # Use the change template instead of the add template.
            add = False

        context.update(extra_context or {})

        return self.render_change_form(request, context, add=add, change=not add, obj=obj, form_url=form_url)
