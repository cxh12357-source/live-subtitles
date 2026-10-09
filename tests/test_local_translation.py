"""Optional real-model regression; skipped on machines without the downloaded pack."""
import pytest
from captioner.core import DATA
from captioner.translation import LocalTranslator


@pytest.mark.skipif(not (DATA/'translation/en_zh/model/model.bin').exists(),reason='English→Chinese model not installed')
def test_real_translation_has_no_tokenizer_markers():
    result=LocalTranslator().translate('Hello everyone. The weather is beautiful today.','en','zh')
    assert '▁' not in result
    assert any('\u4e00'<=c<='\u9fff' for c in result)


def test_chinese_target_is_simplified(tmp_path):
    assert LocalTranslator(tmp_path).translate('歡迎觀看電腦字幕','zh','zh')=='欢迎观看电脑字幕'
