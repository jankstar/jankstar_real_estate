from trytond.model import ModelSQL, fields

class User(ModelSQL):
    'User'
    __name__ = 'res.user'

    phone = fields.Char('Phone', translate=False, autocomplete=False)
    mobile = fields.Char('Mobile', translate=False, autocomplete=False)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._context_fields.insert(0, 'phone')
        cls._context_fields.insert(0, 'mobile')

    @classmethod
    def _get_preferences(cls, user, context_only=False):
        preferences = super()._get_preferences(user, context_only=context_only)
        if user.phone:
            preferences['phone'] = user.phone
        if user.mobile:
            preferences['mobile'] = user.mobile
        return preferences