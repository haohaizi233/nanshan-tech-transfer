"""第二阶段修复的回归测试：检索召回、重排、幻觉防护。

每个用例对应一个已修复的真实缺陷，测试名即缺陷描述。

覆盖的缺陷：
1.  候选池按 created_at 截断 50 → 高相关历史成果被挤出
2.  同义词 OR 爆炸 → 候选池被宽松命中污染
3.  价格硬过滤把整库清空（222/223 条为「面议」）
4.  相关度下沉 SQL 后每行重复拼接字段 → P95 从 12ms 涨到 145ms
5.  生产库 GBK collation 下 ILIKE 走 locale 感知比较 → P95 再涨到 90ms+
6.  成熟度裸等级被当成硬下限（04_pilot_done 之下仍返回 10 条）
7.  重排候选投影泄露联系方式
8.  重排返回不存在的候选 ID
9.  advisor 编造证据与数字
10. 零结果时给出编造的"库里没有"结论
"""
import unittest
from unittest.mock import MagicMock, patch

from app.advisor import grounded_explanation
from app.reranker import _achievement_for_llm, _demand_for_llm, rerank_results
from app.services import retrieval, taxonomy
from app.services.amount_parser import find_amount_bounds
from app.services.achievement_service import search_achievements
from app.services.demand_service import search_demands


def _mock_db(rows):
    database = MagicMock()
    cursor = database.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = rows
    return database, cursor


class RetrievalSqlStructureTests(unittest.TestCase):
    """SQL 结构契约：这些是性能修复的载体，结构变了性能就会退化。"""

    def test_filter_escape_literals_are_valid_postgres_strings(self):
        for name, search, options in (
            ("achievement_service", search_achievements, {"organization": "测试"}),
            ("demand_service", search_demands, {"organization": "测试", "region": "深圳", "coop_modes": ["技术转让"]}),
        ):
            database, cursor = _mock_db([])
            with patch(f"app.services.{name}.get_db", return_value=database):
                search(keywords=["视觉"], **options)
            sql = cursor.execute.call_args.args[0]
            self.assertNotIn("ESCAPE E'\\'", sql)
            self.assertIn("ESCAPE E'\\\\'", sql)

    def _search(self, module, fn, **kwargs):
        database, cursor = _mock_db([])
        with patch.object(module, "get_db", return_value=database):
            fn(**kwargs)
        return cursor.execute.call_args.args[0], cursor.execute.call_args.args[1]

    def test_achievement_query_materializes_the_searchable_column(self):
        """缺陷 1/4：必须用 MATERIALIZED CTE，否则规划器会把表达式下推回基表。"""
        database, cursor = _mock_db([])
        with patch("app.services.achievement_service.get_db", return_value=database):
            search_achievements(keywords=["人工智能"])
        sql = cursor.execute.call_args.args[0]
        self.assertIn("WITH base AS MATERIALIZED", sql)
        self.assertIn(taxonomy.SEARCHABLE_COLUMN, sql)

    def test_demand_query_materializes_the_searchable_column(self):
        database, cursor = _mock_db([])
        with patch("app.services.demand_service.get_db", return_value=database):
            search_demands(keywords=["工业质检"])
        sql = cursor.execute.call_args.args[0]
        self.assertIn("WITH base AS MATERIALIZED", sql)

    def test_base_filters_are_pushed_into_the_cte(self):
        """缺陷 4：状态过滤必须下推，否则 CTE 仍要对全表每行做字符串拼接。"""
        database, cursor = _mock_db([])
        with patch("app.services.achievement_service.get_db", return_value=database):
            search_achievements(keywords=["人工智能"])
        sql = cursor.execute.call_args.args[0]
        cte_body = sql.split("FROM base")[0]
        self.assertIn("status = 'published'", cte_body)
        self.assertIn("deleted_at IS NULL", cte_body)

    def test_searchable_column_uses_explicit_c_collation(self):
        """缺陷 5：生产库是 GBK collation，ILIKE 在其上慢 3.5 倍。"""
        database, cursor = _mock_db([])
        with patch("app.services.achievement_service.get_db", return_value=database):
            search_achievements(keywords=["人工智能"])
        sql = cursor.execute.call_args.args[0]
        self.assertIn('COLLATE "C"', sql)

    def test_relevance_and_keyword_conditions_use_explicit_collation(self):
        """缺陷 5：ILIKE 比较的两侧都必须显式指定排序规则。"""
        plan = retrieval.build_term_plan(["人工智能"], taxonomy.KEYWORD_EXPANSIONS)
        relevance_sql, _ = retrieval.relevance_expression("achievement", plan)
        keyword_sql, _ = retrieval.keyword_condition("achievement", plan)
        self.assertIn('COLLATE "C"', relevance_sql)
        self.assertIn('COLLATE "C"', keyword_sql)

    def test_candidate_pool_is_ordered_by_relevance_not_creation_time(self):
        """缺陷 1：候选池必须按相关度排序，created_at 只能作同分次级键。"""
        database, cursor = _mock_db([])
        with patch("app.services.achievement_service.get_db", return_value=database):
            search_achievements(keywords=["人工智能"])
        sql = cursor.execute.call_args.args[0]
        self.assertIn("ORDER BY _rel DESC, created_at DESC", sql)

    def test_searchable_column_does_not_leak_into_result_dict(self):
        """物化列只服务于 SQL 内部，不能出现在返回给上层的字典里。"""
        database, cursor = _mock_db([{
            "id": 1, "title": "t", "created_at": "2026-01-01",
            "_searchable": "内部检索文本", "_rel": 24,
        }])
        with patch("app.services.achievement_service.get_db", return_value=database):
            results = search_achievements(keywords=["人工智能"])
        self.assertNotIn(taxonomy.SEARCHABLE_COLUMN, results[0])
        self.assertEqual(results[0]["_score"], 24)

    def test_parameter_order_matches_placeholder_order(self):
        """CTE 参数在前、相关度次之、关键词再次之、LIMIT 最后。"""
        database, cursor = _mock_db([])
        with patch("app.services.achievement_service.get_db", return_value=database):
            search_achievements(
                keywords=["人工智能"],
                organization="某研究院",
                min_price_wan=10,
                max_price_wan=100,
                min_maturity="03_pilot_ready",
                exclude_owner_user_id=7,
            )
        sql, params = cursor.execute.call_args.args
        self.assertEqual(sql.count("%s"), len(params))
        # 最后一个参数是 LIMIT
        self.assertEqual(params[-1], 50)
        # exclude_owner_user_id 是 CTE 内的第一个业务参数
        self.assertEqual(params[0], 7)


class RetrievalSemanticsTests(unittest.TestCase):
    """召回语义：硬性条件、区间重叠、词条分层。"""

    def test_unknown_price_is_not_treated_as_price_mismatch(self):
        """缺陷 3：生产库 222/223 条成果报价为「面议」，旧语义会把整库过滤干净。"""
        self.assertTrue(taxonomy.amount_band_matches(None, None, None, 100))
        self.assertFalse(taxonomy.amount_band_matches(200, 300, None, 100))
        self.assertTrue(taxonomy.amount_band_matches(50, 80, None, 100))

    def test_invalid_price_is_excluded_fail_closed(self):
        """非法数值是数据损坏，必须排除而不是放行。"""
        self.assertFalse(taxonomy.amount_band_matches(float("nan"), None, None, 100))
        self.assertFalse(taxonomy.amount_band_matches(None, float("inf"), None, 100))

    def test_amount_condition_keeps_unknown_price_rows(self):
        sql, params = retrieval.amount_condition(None, 100.0, "price_min_wan", "price_max_wan")
        self.assertIn("price_min_wan IS NULL", sql)
        self.assertIn("price_max_wan IS NULL", sql)
        self.assertEqual(params, [100.0])

    def test_literal_terms_outweigh_expanded_terms(self):
        """缺陷 2：用户原词系数 3，同义扩展系数 1。"""
        plan = retrieval.build_term_plan(["人工智能"], taxonomy.KEYWORD_EXPANSIONS)
        weighted = dict(plan.weighted())
        self.assertEqual(weighted["人工智能"], taxonomy.LITERAL_TERM_MULTIPLIER)
        self.assertEqual(weighted["机器学习"], taxonomy.EXPANDED_TERM_MULTIPLIER)

    def test_expanded_term_count_is_bounded(self):
        """缺陷 2：扩展词数量必须受控，否则 ILIKE 谓词爆炸。"""
        plan = retrieval.build_term_plan(["人工智能"], taxonomy.KEYWORD_EXPANSIONS)
        self.assertLessEqual(len(plan.expanded), taxonomy.MAX_EXPANDED_TERMS)

    def test_maturity_hard_filter_is_not_applied_from_bare_level(self):
        """缺陷 6：'04_pilot_done' 不是下限等级，硬过滤会返回错误集合。"""
        self.assertTrue(taxonomy.maturity_at_least("05_mass_ready", "04_pilot_done"))
        self.assertFalse(taxonomy.maturity_at_least("02_lab", "04_pilot_done"))
        self.assertFalse(taxonomy.maturity_at_least(None, "04_pilot_done"))

    def test_maturity_order_is_monotonic(self):
        levels = list(taxonomy.MATURITY_ORDER)
        for index, level in enumerate(levels):
            for later in levels[index:]:
                self.assertTrue(taxonomy.maturity_at_least(later, level))


class RerankerProjectionTests(unittest.TestCase):
    """缺陷 7/8：候选投影与 ID 校验。"""

    def test_achievement_candidate_projection_excludes_contact_info(self):
        item = {
            "id": 1, "title": "t", "source_org_name": "org",
            "contact_name": "张三", "contact_phone": "13800001111",
            "contact_email": "z@example.com",
        }
        projected = _achievement_for_llm(item)
        self.assertNotIn("contact_name", projected)
        self.assertNotIn("contact_phone", projected)
        self.assertNotIn("contact_email", projected)

    def test_demand_candidate_projection_excludes_contact_info(self):
        item = {
            "id": 2, "title": "t", "org_name_snapshot": "org",
            "contact_name": "李四", "contact_phone": "13900002222",
            "contact_email": "l@example.com",
        }
        projected = _demand_for_llm(item)
        self.assertNotIn("contact_name", projected)
        self.assertNotIn("contact_phone", projected)
        self.assertNotIn("contact_email", projected)

    def test_reranker_drops_ids_that_are_not_in_the_candidate_pool(self):
        """缺陷 8：模型可能返回不存在的 ID，必须丢弃。"""
        candidates = [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}]
        with patch("app.reranker._call_reranker", return_value={
            "results": [{"id": 1}, {"id": 999}, {"id": 2}],
        }):
            results = rerank_results(
                intent="search_achievement", user_message="找成果", candidates=candidates,
            )
        ids = [item.get("id") for item in results]
        self.assertNotIn(999, ids)
        self.assertTrue(set(ids).issubset({1, 2}))

    def test_reranker_fills_missing_candidates_from_the_pool(self):
        """候选不足时补齐，避免模型漏排导致结果变少。"""
        candidates = [{"id": i, "title": f"t{i}"} for i in range(1, 6)]
        with patch("app.reranker._call_reranker", return_value={"results": [{"id": 1}]}):
            results = rerank_results(
                intent="search_achievement", user_message="找成果", candidates=candidates, top_n=5,
            )
        self.assertEqual(len(results), 5)

    def test_soft_preference_never_removes_a_hard_filtered_candidate(self):
        """软偏好只影响排序，不得突破硬性条件（候选池本身已不含违规项）。"""
        candidates = [{"id": 1, "title": "t", "view_count": 100}]
        with patch("app.reranker._call_reranker", return_value={"results": [{"id": 1}]}):
            results = rerank_results(
                intent="search_achievement", user_message="找成果",
                candidates=candidates, preferences=["prefer_popular"],
            )
        self.assertEqual([item["id"] for item in results], [1])


class GroundingTests(unittest.TestCase):
    """缺陷 9：advisor 不允许虚构证据与数字。"""

    ITEM = {
        "id": 1,
        "title": "基于视觉的工业质检系统",
        "tech_intro": "可用于金属表面缺陷检测，识别准确率 99.2%。",
        "application_fields": ["汽车制造"],
        "innovation_points": ["采用多尺度特征融合"],
    }

    def test_evidence_quote_must_appear_verbatim(self):
        evidence, _ = grounded_explanation(
            {"evidence": [{"field": "tech_intro", "quote": "识别准确率 99.9%"}], "analysis": []},
            self.ITEM,
        )
        self.assertEqual(evidence, [])

    def test_evidence_quote_from_source_is_accepted(self):
        evidence, _ = grounded_explanation(
            {"evidence": [{"field": "tech_intro", "quote": "识别准确率 99.2%"}], "analysis": []},
            self.ITEM,
        )
        self.assertEqual(len(evidence), 1)

    def test_analysis_numbers_must_exist_in_the_source(self):
        _, analysis = grounded_explanation(
            {"evidence": [], "analysis": "可降低成本 30%"},
            self.ITEM,
        )
        self.assertEqual(analysis, "")

    def test_analysis_number_from_source_is_accepted(self):
        _, analysis = grounded_explanation(
            {
                "evidence": [{"field": "tech_intro", "quote": "识别准确率 99.2%"}],
                "analysis": "识别准确率 99.2%，可用于产线质检",
            },
            self.ITEM,
        )
        self.assertTrue(analysis)

    def test_analysis_without_evidence_is_dropped(self):
        """没有原文引用支撑的解读一律丢弃——这是幻觉防护的最后一道闸。"""
        _, analysis = grounded_explanation(
            {"evidence": [], "analysis": "识别准确率 99.2%，可用于产线质检"},
            self.ITEM,
        )
        self.assertEqual(analysis, "")

    def test_evidence_field_must_be_in_the_allowlist(self):
        evidence, _ = grounded_explanation(
            {"evidence": [{"field": "contact_phone", "quote": "13800001111"}], "analysis": []},
            self.ITEM,
        )
        self.assertEqual(evidence, [])


class AmountParserTests(unittest.TestCase):
    """金额解析在 router 与 reranker 之间必须共享同一实现。"""

    def test_upper_bound_is_extracted(self):
        self.assertEqual(find_amount_bounds("100万以内").get("max_wan"), 100)

    def test_no_amount_returns_none(self):
        self.assertEqual(find_amount_bounds("找机器视觉成果").get("max_wan"), None)


if __name__ == "__main__":
    unittest.main()
