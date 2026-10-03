'ir.cron extension for Real Estate'
from trytond.pool import PoolMeta
from trytond.transaction import Transaction


class Cron(metaclass=PoolMeta):
    __name__ = 'ir.cron'

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.method.selection.append(
            ('real_estate.contract|cron_daily', "Real Estate Daily Tasks"))


class Rule(metaclass=PoolMeta):
    __name__ = 'ir.rule'

    # The record rules of Tryton only know the user's groups - the
    # task rule "assigned to me" (spezifikation-wiedervorlage.md 13.4)
    # needs the user id, also as part of the rule cache key

    @classmethod
    def _get_context(cls, model_name):
        context = super()._get_context(model_name)
        context['user_id'] = Transaction().user
        return context

    @classmethod
    def _get_cache_key(cls, model_names):
        key = super()._get_cache_key(model_names)
        return (key, Transaction().user)
