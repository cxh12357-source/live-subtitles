"""One ordered subtitle, independent of recognition and translation workers."""
from opencc import OpenCC

_simplified = OpenCC('t2s')


def display_text(text, language=None):
    # Font selection is deliberately separate from character conversion.
    return text if language in ('ja','ko') else _simplified.convert(text)


class CurrentCaption:
    def __init__(self):
        self.reset('', 0)

    def reset(self, session, epoch):
        self.session, self.epoch = session, epoch
        self.caption = None
        self.order = (-1, -1, -1, -1, False)
        self.confirmed = False
        self.expired = False
        self.translation_revision = -1
        self.translation_source = ''

    @staticmethod
    def key(c):
        return c.session, c.epoch, c.id

    def accept(self, c, final):
        if (c.session, c.epoch) != (self.session, self.epoch):
            return False
        order = (c.start, c.id, c.revision, c.end, final)
        if order <= self.order:
            return False
        same = self.caption is not None and self.key(c) == self.key(self.caption)
        if same and ((self.expired and c.end <= self.caption.end+.05) or (self.confirmed and not final)):
            return False
        if same and self.translation_source and c.text.startswith(self.translation_source):
            c.translation=self.caption.translation
        elif not same or self.translation_source:
            self.translation_revision=-1;self.translation_source=''
        self.caption, self.order, self.confirmed, self.expired = c, order, final, False
        return True

    def translate(self, session, epoch, ident, revision, text, source='', produced_at=None):
        c = self.caption
        if (self.expired or c is None or
            (session,epoch,ident)!=(c.session,c.epoch,c.id) or revision>c.revision or
            revision<self.translation_revision):
            return False
        if source:
            if not c.text.startswith(source):return False
        elif revision!=c.revision:return False
        c.translation = text
        self.translation_revision=revision;self.translation_source=source or c.text
        if produced_at is not None:c.timing['translation_produced_at']=produced_at
        return True

    def text(self, mode, target):
        c = self.caption
        if c is None or self.expired:
            return ''
        original = display_text(c.text,c.language)
        # Chinese speech -> Chinese output is transcription, never cross-language MT.
        translated = display_text(c.translation or (c.text if c.language == target else ''),target)
        if mode == 'original': return original
        if mode == 'translation': return translated
        if translated and translated != original: return original + '\n' + translated
        return original
