import datetime

from trytond.model import fields
from trytond.pool import PoolMeta
from trytond.pyson import Eval

class Sequence(metaclass=PoolMeta):
    __name__ = 'ir.sequence'


    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.type.selection.append(('string timestamp', 'String Timestamp'))
        cls.timestamp_rounding.states={
            'invisible': ~Eval('type').in_(
                ['decimal timestamp', 'string timestamp', 'hexadecimal timestamp']),
            }
        cls.timestamp_offset.states={
            'invisible': ~Eval('type').in_(
                ['decimal timestamp', 'string timestamp', 'hexadecimal timestamp']),
            }
        cls.last_timestamp.states={
            'invisible': ~Eval('type').in_(
                ['decimal timestamp', 'string timestamp', 'hexadecimal timestamp']),
            'required': Eval('type').in_(
                ['decimal timestamp', 'string timestamp', 'hexadecimal timestamp']),
            }
    @classmethod
    def view_attributes(cls):
        return [
            ('//group[@id="incremental"]', 'states', {
                    'invisible': ~Eval('type').in_(['incremental']),
                    }),
            ('//group[@id="timestamp"]', 'states', {
                    'invisible': ~Eval('type').in_(
                        ['decimal timestamp', 'string timestamp', 'hexadecimal timestamp']),
                    }),
            ]        

    def _get_many(self, n=1):
        if self.type == 'string timestamp':
            timestamps = []
            last_timestamp = timestamp = self.last_timestamp
            for _ in range(n):
                while timestamp == last_timestamp:
                    timestamp = self._timestamp()
                timestamps.append(timestamp)
                last_timestamp = timestamp
            self.last_timestamp = last_timestamp
            self.save()    
            for timestamp in timestamps:
                    yield datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')        
        else:   
            return super()._get_many(n)
        
        @fields.depends('type', 'padding', 'number_next', methods=['_timestamp'])
        def _get_preview_sequence(self):
            if self.type == 'string timestamp':
                timestamp = self._timestamp()
                return datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            else:
                return super()._get_preview_sequence()
                            