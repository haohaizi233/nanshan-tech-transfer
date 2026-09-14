"""Vite Vue SFC 查询串必须原样转发，不能走 QueryParams 序列化。"""

from starlette.datastructures import QueryParams

from app import _h5_dev_url

VUE_STYLE_QUERY = "vue&type=style&index=0&lang.scss"


def test_h5_dev_url_keeps_vue_sfc_flag_query():
    url = _h5_dev_url("App.vue", VUE_STYLE_QUERY)
    assert url == f"http://127.0.0.1:5173/h5/App.vue?{VUE_STYLE_QUERY}"


def test_query_params_str_mangles_vue_flag():
    mangled = str(QueryParams(VUE_STYLE_QUERY))
    assert mangled != VUE_STYLE_QUERY
    assert mangled.startswith("vue=")


if __name__ == "__main__":
    test_h5_dev_url_keeps_vue_sfc_flag_query()
    test_query_params_str_mangles_vue_flag()
    print("ok")
