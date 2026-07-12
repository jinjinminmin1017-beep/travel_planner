from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import escape


OUT = Path("docs/AIRLINE_OFFICIAL_SITE_TECH_CHECK_20260705.xlsx")

HEADERS = [
    "序号",
    "航司代码",
    "航司/品牌",
    "官网或确认入口",
    "入口归属/系统族",
    "首页匿名可达",
    "robots确认",
    "订票/航班查询入口",
    "前端资源/API线索",
    "票价字段线索",
    "航班时间字段线索",
    "余票/舱位字段线索",
    "验证码/风控信号",
    "是否可继续真实查询取样",
    "Provider建议",
    "优先级",
    "技术结论",
    "下一步",
]

ROWS = [
    [1, "CA", "中国国际航空", "https://www.airchina.com.cn", "国航官网 / Next.js", "200，匿名可达", "404", "首页有机票/订票/航班入口信号", "_next 静态资源，需继续解析 JS 请求", "页面级线索，未确认查询响应字段", "页面级线索，未确认查询响应字段", "未确认", "未见入口层验证码", "是", "airline_ca_public_query", "P1", "可继续；需解析 Next.js 前端查询接口", "抓取首页 JS，定位低频匿名查询请求并做黄金样本"],
    [2, "MU", "中国东方航空", "https://www.ceair.com/zh/cny/home", "东航官网", "200，匿名可达", "404", "首页有机票/订票/航班入口信号", "前端应用壳，入口层未暴露明显候选链接", "页面级线索，未确认查询响应字段", "页面级线索，未确认查询响应字段", "未确认", "未见入口层验证码", "是", "airline_mu_public_query", "P0", "可继续；当前项目已预留 MU source_id", "用浏览器网络面板确认查询 JSON 或 embedded 数据"],
    [3, "CZ", "中国南方航空", "https://www.csair.com", "南航官网", "200，匿名可达", "200", "首页有机票/预订/航班信号", "入口层未暴露明显候选链接", "页面级线索，未确认查询响应字段", "页面级线索，未确认查询响应字段", "未确认", "未见入口层验证码", "是", "airline_cz_public_query", "P0", "可继续；当前项目已预留 CZ source_id", "用浏览器网络面板确认查询 JSON 或 embedded 数据"],
    [4, "HU", "海南航空", "https://www.hnair.com", "海航官网", "200，匿名可达", "200 但跳转 404 页面", "首页订票入口明显", "ticket_box.js / airport.js / ticketCheck-service.js", "JS/页面级线索，未提交查询", "JS/页面级线索，未提交查询", "未确认", "未见入口层验证码", "是", "airline_hna_public_query", "P1", "可继续；可能和海航 micro 系分开", "解析 ticket_box/ticketCheck 服务并低频取样"],
    [5, "MF", "厦门航空", "https://www.xiamenair.com/zh-cn/", "厦航官网 / 南航系", "200，匿名可达", "200 但返回首页", "首页未直接暴露明显候选入口", "未发现明显 flight/search 链接", "未确认", "未确认", "未确认", "未见入口层验证码", "需浏览器确认", "airline_mf_public_query", "P2", "需要浏览器渲染确认", "定位查询入口；若复用南航/河北体系则合并 parser"],
    [6, "FM", "上海航空", "https://www.ceair.com", "东航统一入口", "归并 MU", "归并 MU", "归并东航", "归并东航", "归并东航", "归并东航", "归并东航", "归并东航", "否，归并", "airline_mu_public_query", "P0", "不单独做 Provider", "通过 MU Provider 覆盖 FM 航班号"],
    [7, "3U", "四川航空", "https://www.sichuanair.com / https://flights.sichuanair.com", "川航 B2C", "200，匿名可达", "404", "flights.sichuanair.com B2C 入口明显", "B2C 页面/资源含 price/fare/seat/captcha", "有 price/fare 线索", "有 flight 线索", "有 seat/舱线索", "captcha/验证码信号", "是，但高风险", "airline_3u_public_query", "P1", "可继续；查询阶段可能触发验证码", "先确认非验证码路径是否返回查询结果"],
    [8, "ZH", "深圳航空", "https://www.shenzhenair.com/szair_B2C/", "深航 B2C / 国航系", "200，匿名可达", "200 但返回 B2C 首页", "B2C 入口明显", "/szair_B2C/static 资源，有 flight/booking/ticket 信号", "页面级线索", "页面级线索", "未确认", "未见入口层验证码", "是", "airline_zh_public_query", "P1", "可继续", "解析 B2C JS，确认查询接口和字段"],
    [9, "SC", "山东航空", "https://www.sda.cn / https://flights.sda.cn/flight/lowPrice", "山航 flights.sda.cn", "200，匿名可达", "404", "lowPrice / multipleDestinations / selfService 明确", "flights.sda.cn 入口可达", "待真实查询确认", "lowPrice 页面含航班信号", "待真实查询确认", "未见入口层验证码", "是", "airline_sc_public_query", "P0", "最优先；当前项目已预留 SC source_id", "对 SHA/TAO 等样本低频取价，确认 price/cabin/availability"],
    [10, "9C", "春秋航空", "https://www.ch.com / https://flights.ch.com", "春秋 flights.ch.com", "200，匿名可达", "404", "flights.ch.com 明确", "页面含 price/seat/票价/舱/起飞/到达/geetest", "有价格/票价线索", "有起飞/到达线索", "有 seat/舱线索", "geetest/验证码信号", "是，但高风险", "airline_9c_public_query", "P1", "可继续；风控概率高", "确认低频匿名查询是否立即触发 geetest"],
    [11, "HO", "吉祥航空", "https://www.juneyaoair.com/home", "吉祥 B2C", "200，匿名可达", "200", "首页订票入口明显", "staticb2c 资源，加载 gt.js", "页面/JS 线索", "页面/JS 线索", "未确认", "gt.js 信号", "是，但需看风控", "airline_ho_public_query", "P1", "可继续；需确认查询阶段验证码", "解析 staticb2c JS 和查询接口"],
    [12, "KN", "中国联合航空", "https://www.flycua.com", "中联航 / 东航系", "200，匿名可达", "000", "首页有机票弱信号", "未发现明显查询链接", "未确认", "未确认", "未确认", "未确认", "低优先级", "airline_kn_public_query 或并入 MU", "P3", "入口弱，可能归并东航", "优先确认是否可由 MU 覆盖"],
    [13, "JD", "首都航空", "https://www.jdair.net/micro/main/flight/search", "海航 micro", "200，匿名可达", "404", "/micro/main/flight/search 明确", "micro 页面含 price/seat/起飞/到达", "有 price/票价线索", "有起飞/到达线索", "有 seat/舱线索", "未见入口层验证码", "是", "airline_hna_micro_query", "P1", "可继续；可与 8L/UQ/FU/Y8 复用", "做海航 micro parser 黄金样本"],
    [14, "GS", "天津航空", "https://www.tianjin-air.com", "海航系", "200，匿名可达", "200", "首页入口信号弱", "未发现明显入口", "未确认", "未确认", "未确认", "未确认", "需继续找入口", "airline_hna_micro_query", "P2", "可能复用海航 micro", "尝试 /micro/main/flight/search 或官网跳转入口"],
    [15, "8L", "祥鹏航空", "https://www.luckyair.net/micro/main/flight/search", "海航 micro", "200，匿名可达", "404/404页", "/micro/main/flight/search 明确", "micro 页面含 price/seat/flight", "有 price 线索", "有 flight 线索", "有 seat/舱线索", "未见入口层验证码", "是", "airline_hna_micro_query", "P1", "可继续；复用海航 micro", "同 JD"],
    [16, "PN", "西部航空", "https://www.westair.cn", "海航系", "200，匿名可达", "200", "首页入口信号弱", "未发现明显入口", "未确认", "未确认", "未确认", "未确认", "需继续找入口", "airline_hna_micro_query", "P2", "可能复用海航 micro", "尝试 micro 搜索路径和跳转入口"],
    [17, "BK", "奥凯航空", "https://www.okair.net", "奥凯官网", "200，匿名可达", "404", "入口信号弱", "未发现明显查询链接", "未确认", "未确认", "未确认", "未确认", "需浏览器确认", "airline_bk_public_query", "P3", "暂不优先", "人工打开首页查找订票网络请求"],
    [18, "EU", "成都航空", "https://www.chengduair.cc", "成都航官网", "000，本轮匿名失败", "000", "未确认", "未确认", "未确认", "未确认", "未确认", "未确认", "否，需复核", "airline_eu_public_query", "P3", "本轮不可达", "换网络/域名复核后再判断"],
    [19, "G5", "华夏航空", "https://www.chinaexpressair.com", "华夏官网", "200，匿名可达", "404", "入口信号弱", "未发现明显查询链接", "未确认", "未确认", "未确认", "未确认", "需浏览器确认", "airline_g5_public_query", "P3", "暂不优先", "人工确认是否存在公开订票入口"],
    [20, "DZ", "东海航空", "https://www.donghaiair.com", "东海官网", "200，匿名可达", "404", "首页 searchFlight 线索", "searchFlight(route...) / fare 信号", "有 fare/价格线索", "有 flight 信号", "有 seat/舱线索", "未见入口层验证码", "是", "airline_dz_public_query", "P2", "可继续", "定位 searchFlight 调用参数和响应"],
    [21, "NS", "河北航空", "https://www.hbhk.com.cn", "河北航 / 厦航系", "200，匿名可达", "404", "首页有机票/航班信号", "未发现明显查询链接", "页面级线索", "页面级线索", "未确认", "未见入口层验证码", "需继续确认", "airline_ns_public_query 或并入 MF", "P2", "可能归并厦航体系", "确认是否复用厦航 B2C"],
    [22, "KY", "昆明航空", "https://www.airkunming.com", "昆航 / 深航系", "200，匿名可达", "404", "入口信号弱", "未发现明显查询链接", "未确认", "未确认", "未确认", "未确认", "低优先级", "airline_ky_public_query 或并入 ZH", "P3", "可能由深航/国航体系覆盖", "确认是否跳转深航/国航购票"],
    [23, "JR", "幸福航空", "https://www.joy-air.com", "幸福航", "000，本轮匿名失败", "000", "未确认", "未确认", "未确认", "未确认", "未确认", "未确认", "否，需复核", "airline_jr_public_query", "P3", "本轮不可达", "换网络/域名复核"],
    [24, "TV", "西藏航空", "https://www.airxizang.com/stdair/homepage", "stdair 系统", "200，匿名可达", "000", "stdair homepage 明确", "stdair 插件资源，含 base64/UnicodeASNI", "有 price 线索", "有 flight/到达线索", "有 seat/cabin/舱线索", "captcha/验证码信号", "是，但高风险", "airline_stdair_query", "P1", "可继续；stdair 系可复用", "确认 stdair 查询接口是否匿名可用"],
    [25, "GJ", "长龙航空", "https://www.loongair.cn", "长龙官网", "200，匿名可达", "200", "首页有机票/订票信号", "未发现明显查询链接", "未确认", "未确认", "未确认", "未确认", "需浏览器确认", "airline_gj_public_query", "P3", "暂不优先", "人工确认订票入口和接口"],
    [26, "DR", "瑞丽航空", "https://www.rlair.net", "瑞丽官网", "200，匿名可达", "200 但返回 #/404", "首页有机票/航班信号", "未发现明显查询链接", "页面级线索", "页面级线索", "未确认", "未确认", "需浏览器确认", "airline_dr_public_query", "P3", "暂不优先", "确认 SPA 路由和接口"],
    [27, "QW", "青岛航空", "https://www.qdairlines.com", "青岛航空 SPA", "200，匿名可达", "200", "首页订票/flightSearch 明确", "FlightReservation/flightSearch JS 可达", "JS 有 price/票价线索", "JS 有 flight/search 线索", "未确认", "未见入口层验证码", "是", "airline_qw_public_query", "P1", "可继续；JS 线索清晰", "解析 FlightReservation JS 定位接口"],
    [28, "UQ", "乌鲁木齐航空", "https://www.urumqi-air.com/micro/main/flight/search", "海航 micro", "200，匿名可达", "404", "/micro/main/flight/search 明确", "micro 页面含 price/seat/起飞", "有 price/价格线索", "有 flight/起飞线索", "有 seat/舱线索", "未见入口层验证码", "是", "airline_hna_micro_query", "P1", "可继续；复用海航 micro", "同 JD"],
    [29, "FU", "福州航空", "https://www.fuzhou-air.cn/micro/main/flight/search", "海航 micro", "200，匿名可达", "404", "/micro/main/flight/search 明确", "micro 页面含 price/seat/航班", "有 price/价格线索", "有 flight 信号", "有 seat/舱线索", "未见入口层验证码", "是", "airline_hna_micro_query", "P1", "可继续；复用海航 micro", "同 JD"],
    [30, "AQ", "九元航空", "https://www.9air.com", "九元官网", "200，匿名可达", "200", "首页有机票/航班信号", "未发现明显查询链接", "页面级线索", "页面级线索", "未确认", "未见入口层验证码", "需浏览器确认", "airline_aq_public_query", "P3", "暂不优先", "确认官网购票入口和接口"],
    [31, "GX", "北部湾航空", "https://www.gxairlines.com/stdair/homepage", "stdair 系统", "200，匿名可达", "404", "stdair homepage 明确", "stdair 插件资源", "有 price/fare 线索", "有 flight/到达线索", "有 seat/cabin/舱线索", "captcha/验证码信号", "是，但高风险", "airline_stdair_query", "P1", "可继续；stdair 系可复用", "同 TV"],
    [32, "RY", "江西航空", "https://www.airjiangxi.com/jiangxiair/v2/index.action", "江西航入口", "200，匿名可达", "000", "/jiangxiair/v2/index.action 明确", "入口需继续解析", "页面级线索", "未确认", "未确认", "未确认", "需继续确认", "airline_ry_public_query", "P2", "可继续但字段未确认", "解析 v2/index.action 资源"],
    [33, "GY", "多彩贵州航空", "https://www.cgzair.com/yss/commonquery-passengerticket/receptionList", "多彩贵州 yss", "200，匿名可达", "200", "commonquery-passengerticket 明确", "页面含 price/fare/seat/cabin/起飞/到达/geetest", "有 price/fare/票价线索", "有起飞/到达线索", "有 seat/cabin/舱线索", "geetest 信号", "是，但高风险", "airline_gy_public_query", "P1", "可继续；风控概率高", "确认查询是否触发 geetest"],
    [34, "A6", "湖南航空", "https://www.hnair.com", "海航统一入口", "归并 HU", "归并 HU", "归并海航入口", "归并海航入口", "归并海航", "归并海航", "归并海航", "归并海航", "否，归并", "airline_hna_public_query 或 airline_hna_micro_query", "P2", "不单独做 Provider", "通过海航体系覆盖"],
    [35, "GT", "桂林航空", "https://www.airguilin.com/stdair/homepage", "stdair 系统", "200，匿名可达", "404", "stdair homepage 明确", "stdair 插件资源", "有 price/价格线索", "有 flight/到达线索", "有 seat/cabin/舱线索", "captcha/验证码信号", "是，但高风险", "airline_stdair_query", "P1", "可继续；stdair 系可复用", "同 TV"],
    [36, "LT", "龙江航空", "https://www.longjianghk.com", "龙江航官网", "200，匿名可达", "000", "首页有机票/航班信号", "未发现明显查询链接", "页面级线索", "页面级线索", "未确认", "未确认", "低优先级", "airline_lt_public_query", "P3", "暂不优先", "人工确认是否仍有稳定售票入口"],
    [37, "9D", "天骄航空", "https://www.tianjiao-air.com", "天骄航官网", "000，本轮匿名失败", "000", "未确认", "未确认", "未确认", "未确认", "未确认", "未确认", "否，需复核", "airline_9d_public_query", "P3", "本轮不可达", "换网络/域名复核"],
    [38, "Y8", "金鹏航空", "https://www.yzr.com.cn", "海航 micro", "200，匿名可达", "404", "order/search、flight/status 等 micro 入口", "micro 页面含 price/seat/flight", "有 price 线索", "有 flight 信号", "有 seat/舱线索", "未见入口层验证码", "是", "airline_hna_micro_query", "P1", "可继续；复用海航 micro", "找 flight/search 或航线查询入口，复用 parser"],
    [39, "9H", "长安航空", "https://www.airchangan.com", "海航系/长安", "200，匿名可达", "000", "首页有机票/航班信号", "未发现明显查询链接", "页面级线索", "页面级线索", "未确认", "未确认", "需继续确认", "airline_hna_micro_query", "P2", "可能复用海航 micro", "尝试 micro 搜索路径和跳转入口"],
    [40, "OQ", "重庆航空", "https://www.csair.com", "南航统一入口", "归并 CZ", "归并 CZ", "归并南航", "归并南航", "归并南航", "归并南航", "归并南航", "归并南航", "否，归并", "airline_cz_public_query", "P0", "不单独做 Provider", "通过 CZ Provider 覆盖 OQ 航班号"],
]

ITEMS = [
    ["确认项", "说明"],
    ["首页匿名可达", "使用低频 curl 访问官网首页，不提交航线/日期查询；记录 HTTP 状态、跳转和内容类型。"],
    ["robots确认", "访问 /robots.txt 的技术可达性；本表仅作访问限制记录，不替代合规判断。"],
    ["订票/航班查询入口", "首页或公开页面是否暴露订票、航班查询、低价日历、B2C/micro/stdair 等入口。"],
    ["前端资源/API线索", "页面或 JS 是否出现 flight/search/booking/fare/price/seat 等资源或函数线索。"],
    ["票价字段线索", "是否在页面/JS 中发现 price/fare/票价/价格字段或文案；不等同于已拿到真实报价。"],
    ["航班时间字段线索", "是否发现 flight/起飞/到达等字段或文案；不等同于已拿到真实航班列表。"],
    ["余票/舱位字段线索", "是否发现 seat/cabin/舱/availability 等字段或文案；不等同于已确认余票语义。"],
    ["验证码/风控信号", "是否发现 captcha/验证码/geetest/gt.js 等信号；发现后真实查询阶段需特别谨慎。"],
    ["是否可继续真实查询取样", "是否建议进入下一步：以单航线、单日期、低频匿名请求确认真实响应字段。"],
]


def col_name(n: int) -> str:
    name = ""
    while n:
        n, rem = divmod(n - 1, 26)
        name = chr(65 + rem) + name
    return name


def cell_xml(value: object, row_idx: int, col_idx: int, style: int | None = None) -> str:
    ref = f"{col_name(col_idx)}{row_idx}"
    attrs = f' r="{ref}" t="inlineStr"'
    if style is not None:
        attrs += f' s="{style}"'
    text = escape("" if value is None else str(value))
    return f"<c{attrs}><is><t>{text}</t></is></c>"


def sheet_xml(data: list[list[object]], widths: list[int]) -> str:
    rows_xml = []
    for r_idx, row in enumerate(data, start=1):
        style = 1 if r_idx == 1 else 0
        cells = "".join(cell_xml(v, r_idx, c_idx, style) for c_idx, v in enumerate(row, start=1))
        rows_xml.append(f'<row r="{r_idx}">{cells}</row>')
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, start=1))
    auto_filter = f'<autoFilter ref="A1:{col_name(len(data[0]))}{len(data)}"/>'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{cols}</cols><sheetData>{''.join(rows_xml)}</sheetData>{auto_filter}</worksheet>"
    )


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="确认结果" sheetId="1" r:id="rId1"/>'
        '<sheet name="确认项说明" sheetId="2" r:id="rId2"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font>'
        '<font><b/><sz val="11"/><name val="Microsoft YaHei"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
        '<alignment wrapText="1" vertical="top"/></xf><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
        '<alignment wrapText="1" vertical="top"/></xf></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    )
    with ZipFile(OUT, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types.encode("utf-8"))
        z.writestr("_rels/.rels", root_rels.encode("utf-8"))
        z.writestr("xl/workbook.xml", workbook.encode("utf-8"))
        z.writestr("xl/_rels/workbook.xml.rels", rels.encode("utf-8"))
        z.writestr("xl/styles.xml", styles.encode("utf-8"))
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml([HEADERS] + ROWS, [6, 10, 18, 48, 24, 18, 20, 32, 42, 24, 24, 24, 22, 24, 30, 10, 34, 44]).encode("utf-8"))
        z.writestr("xl/worksheets/sheet2.xml", sheet_xml(ITEMS, [24, 100]).encode("utf-8"))


if __name__ == "__main__":
    build()
    print(OUT.resolve())
