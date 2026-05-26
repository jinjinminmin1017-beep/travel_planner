import { expect, test } from "@playwright/test";

const sampleInput =
  "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。";

test("plans Shanghai to Qingdao, shows details, recalculates, and redirects", async ({ page }) => {
  await page.route("**/api/data-sources/status", async (route) => {
    await route.fulfill({
      json: {
        schema_version: "1.15",
        sources: [
          { source_id: "mock_map", source_name: "Mock Map Provider", source_type: "MAP", status: "OK", degraded: false, average_latency_ms: 12 },
          { source_id: "mock_rail", source_name: "Mock Rail Provider", source_type: "RAIL", status: "OK", degraded: false, average_latency_ms: 10 }
        ]
      }
    });
  });

  await page.route("**/api/travel/plan", async (route) => {
    await route.fulfill({ json: buildPlanResponse() });
  });

  await page.route("**/api/travel/recalculate", async (route) => {
    const response = buildPlanResponse();
    const plan = response.plans[0];
    plan.cost_breakdown.total_cost = { amount_minor: 88600, currency: "CNY", scale: 2, is_estimated: false, display_text: "¥886.00" };
    plan.comfort_score.total_score = 8.9;
    await route.fulfill({
      json: {
        schema_version: "1.15",
        plan,
        change_summary: {
          cost_delta: { amount_minor: 22000, display_text: "+¥220.00" },
          duration_delta_minutes: 0,
          comfort_delta: 1,
          message: "已基于后端返回的合法 option_id 完成重算。"
        }
      }
    });
  });

  await page.route("**/api/redirect/booking", async (route) => {
    await route.fulfill({
      json: {
        redirect: {
          redirect_id: "redir_test",
          redirect_type: "RAIL_12306",
          transaction_boundary: "REDIRECT_ONLY",
          url_available: false,
          url: null,
          fallback_instruction: "请打开 12306 手动确认。",
          data_source: source("mock_rail", "Mock Rail Provider", "RAIL"),
          generated_at: timePoint()
        }
      }
    });
  });

  await page.goto("/");
  await expect(page.getByText("AI 出行规划器")).toBeVisible();
  await page.getByRole("textbox").fill(sampleInput);
  await page.getByRole("button", { name: /开始规划/ }).click();

  await expect(page.getByText("最优惠")).toBeVisible();
  await expect(page.getByText("最舒适")).toBeVisible();
  await expect(page.getByText("综合推荐")).toBeVisible();
  await expect(page.getByText("候选方案")).toBeVisible();
  await expect(page.getByRole("button", { name: /安全关键数据缺失 BLOCKED/ })).toBeVisible();

  await page.getByRole("button", { name: /查看详情/ }).first().click();
  await expect(page.getByText("费用明细")).toBeVisible();
  await page.getByRole("button", { name: /一等座/ }).first().click();
  await expect(page.getByText("+¥220.00")).toBeVisible();

  await page.getByTitle("生成跳转").click();
  await expect(page.getByText("请打开 12306 手动确认。")).toBeVisible();
});

function timePoint() {
  return { datetime: "2026-05-27T08:00:00+08:00", timezone: "Asia/Shanghai", source_timezone: "Asia/Shanghai" };
}

function source(source_id: string, source_name: string, source_type: string) {
  return {
    source_id,
    source_name,
    source_type,
    authority_level: "B",
    license_status: "APPROVED",
    commercial_allowed: false,
    fetched_at: timePoint(),
    update_frequency: "STATIC_MOCK",
    cacheable: true
  };
}

function money(amount_minor: number, display_text: string) {
  return { amount_minor, currency: "CNY", scale: 2, is_estimated: false, display_text };
}

function buildPlanResponse() {
  const railSource = source("mock_rail", "Mock Rail Provider", "RAIL");
  const taxiSource = source("mock_taxi", "Mock Taxi Provider", "TAXI");
  const internalSource = source("internal_calc", "Internal Calculator", "INTERNAL_CALCULATION");
  const plan = {
    schema_version: "1.15",
    plan_id: "plan_rail_direct_shqd",
    plan_name: "打车 + 高铁直达 + 打车",
    plan_type: "DIRECT_RAIL",
    recommendation_eligibility: "ELIGIBLE",
    can_be_selected_by_llm: true,
    block_reason_code: null,
    block_reason_message: null,
    total_duration_minutes: 420,
    cost_breakdown: {
      total_cost: money(66600, "¥666.00"),
      items: [
        { label: "接驳", amount: money(7800, "¥78.00"), data_source: taxiSource },
        { label: "G234 二等座", amount: money(52600, "¥526.00"), data_source: railSource },
        { label: "接驳", amount: money(6200, "¥62.00"), data_source: taxiSource }
      ]
    },
    comfort_score: {
      total_score: 7.9,
      breakdown: { 换乘复杂度: 8, 等待压力: 7.9, 时间友好度: 7.6 },
      confidence: 0.95,
      explanation: "高铁直达换乘少。"
    },
    risk_assessment: {
      overall_risk_level: "LOW",
      recommendation_allowed: true,
      risk_items: [{ risk_id: "risk_1", risk_level: "LOW", title: "直达风险低", message: "接驳风险可控。" }]
    },
    data_quality: { completeness_score: 0.96, missing_components: [], warnings: [] },
    data_sources: [railSource, taxiSource, internalSource],
    booking_redirects: [],
    segments: [
      {
        segment_id: "seg_origin_station",
        segment_type: "LOCAL_TRANSFER",
        origin: "上海嘉定南翔格林公馆",
        destination: "上海虹桥站",
        transfer_mode: "TAXI",
        duration_minutes: 38,
        estimated_cost: money(7800, "¥78.00"),
        option_id: "transfer_taxi",
        available_options: ["transfer_taxi", "transfer_subway"],
        data_source: taxiSource
      },
      {
        segment_id: "seg_rail_direct",
        segment_type: "RAIL",
        train_number: "G234",
        origin_station: "上海虹桥",
        destination_station: "青岛北",
        duration_minutes: 350,
        departure_time: timePoint(),
        arrival_time: timePoint(),
        seat_options: [
          { option_id: "seat_second", seat_type: "二等座", price: money(52600, "¥526.00"), availability: "AVAILABLE", source_option_version: "mock_v1" },
          { option_id: "seat_first", seat_type: "一等座", price: money(74600, "¥746.00"), availability: "AVAILABLE", source_option_version: "mock_v1" }
        ],
        selected_seat_option_id: "seat_second",
        data_source: railSource
      },
      {
        segment_id: "seg_station_dest",
        segment_type: "LOCAL_TRANSFER",
        origin: "青岛北站",
        destination: "青岛金水假日酒店",
        transfer_mode: "TAXI",
        duration_minutes: 32,
        estimated_cost: money(6200, "¥62.00"),
        option_id: "transfer_taxi",
        available_options: ["transfer_taxi", "transfer_subway"],
        data_source: taxiSource
      }
    ]
  };
  return {
    schema_version: "1.15",
    request_id: "req_e2e",
    trace_id: "trace_e2e",
    correlation_id: "corr_e2e",
    idempotency_key: "idem_e2e",
    planning_status: "COMPLETE",
    progress: 100,
    travel_request: {
      schema_version: "1.15",
      request_id: "req_e2e",
      raw_user_input: sampleInput,
      origin_text: "上海嘉定南翔格林公馆",
      destination_text: "青岛金水假日酒店",
      travel_date: "2026-05-21",
      preferences: ["CHEAPEST", "MOST_COMFORTABLE", "BALANCED"],
      preference_source: "SYSTEM_DEFAULT",
      hard_constraints: {},
      soft_preferences: {}
    },
    plans: [
      plan,
      {
        ...plan,
        plan_id: "plan_blocked_shqd",
        plan_name: "安全关键数据缺失 BLOCKED",
        recommendation_eligibility: "BLOCKED",
        can_be_selected_by_llm: false,
        block_reason_code: "SAFETY_CRITICAL_MISSING",
        block_reason_message: "安全关键数据缺失，不能进入推荐候选池。",
        risk_assessment: { ...plan.risk_assessment, overall_risk_level: "BLOCKED", recommendation_allowed: false }
      }
    ],
    recommendation_result: {
      recommendations: [
        { schema_version: "1.15", recommendation_type: "CHEAPEST", status: "AVAILABLE", plan_id: "plan_rail_direct_shqd", reason: "总费用最低。" },
        { schema_version: "1.15", recommendation_type: "MOST_COMFORTABLE", status: "AVAILABLE", plan_id: "plan_rail_direct_shqd", reason: "舒适度较高。" },
        { schema_version: "1.15", recommendation_type: "BALANCED", status: "AVAILABLE", plan_id: "plan_rail_direct_shqd", reason: "综合平衡。" }
      ],
      llm_validation_result: { final_strategy: "USE_ORIGINAL", invalid_reasons: [] }
    },
    source_failures: [{ failure_id: "fail_1", user_visible_message: "部分航班前序风险数据缺失。", impacted_plan_types: ["TRANSFER_FLIGHT"] }],
    missing_components: ["previous_flight_risk"],
    blocked_plan_types: ["TRANSFER_RAIL"],
    user_visible_warnings: ["价格和余票以最终平台为准。"]
  };
}
