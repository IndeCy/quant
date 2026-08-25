"""内置产业机会观察池登记。"""

from __future__ import annotations

from runtime.repository import SystemRepository


def register_builtin_opportunity_themes(repository: SystemRepository) -> None:
    """登记默认机会观察池，不产生交易信号。"""
    _register_theme(
        repository,
        {
            "theme_id": "ai_optical_module_powerlaw",
            "name": "AI光模块历史校准案例",
            "status": "case_study",
            "stage": "LateConfirmed",
            "horizon_years": 10,
            "thesis_type": "case_study_power_law",
            "thesis": "AI光模块用于校准长期右偏机会的早期识别信号，不作为当前未来十年新机会主答案。",
            "upgrade_rule": "仅用于复盘早期信号，不自动升级为新策略；真正候选必须处于早期起势且未高度兑现。",
            "disconfirm_rule": "如果复盘发现早期信号无法在历史上提前出现，则降低该雷达规则权重。",
            "linked_note_id": "strategy_powerlaw_industry_20260701",
            "tags": ["AI算力", "光模块", "产业右偏", "历史样本", "已兑现"],
        },
        [
            ("300308.SZ", "中际旭创", "核心龙头", "高", "高端光模块龙头，AI算力需求和800G/1.6T代际升级核心样本。"),
            ("300502.SZ", "新易盛", "高弹性二线", "高", "高速光模块高弹性标的，财务加速和价格弹性强。"),
            ("300394.SZ", "天孚通信", "核心瓶颈", "中", "光器件环节高毛利样本，关注是否受益于产业链瓶颈。"),
            ("601138.SH", "工业富联", "下游系统集成", "中", "AI服务器和算力硬件链代表，收入体量大但利润率结构不同。"),
            ("000063.SZ", "中兴通讯", "对照样本", "低", "通信设备基础标的，可作为同链路低估值对照样本。"),
        ],
    )
    _register_theme(
        repository,
        _seed_theme(
            "humanoid_robotics_components",
            "人形机器人核心部件",
            "机器人运动控制、执行器、传感器和热管理可能随产业化阶段出现非线性放量。",
            ["人形机器人", "执行器", "传感器", "运动控制"],
        ),
        [
            ("603728.SH", "鸣志电器", "空心杯/运动控制", "中", "电机和运动控制环节样本，观察机器人小型执行器放量验证。"),
            ("688017.SH", "绿的谐波", "减速器", "中", "精密减速器样本，观察国产核心部件渗透率。"),
            ("603662.SH", "柯力传感", "传感器", "中", "力传感和工业传感样本，观察触觉/力控需求。"),
            ("601689.SH", "拓普集团", "结构件/执行器", "中", "汽车零部件向机器人执行器延展样本。"),
            ("002050.SZ", "三花智控", "热管理/机电", "中", "热管理与机电控制能力外溢样本。"),
        ],
    )
    _register_theme(
        repository,
        _seed_theme(
            "domestic_ai_compute_infrastructure",
            "国产算力基础设施",
            "国产算力芯片、服务器和软硬件生态在供给约束下可能形成长期替代机会。",
            ["国产算力", "AI芯片", "服务器", "基础软件"],
        ),
        [
            ("688256.SH", "寒武纪", "AI芯片", "中", "国产AI芯片代表，观察收入兑现和生态扩张。"),
            ("688041.SH", "海光信息", "CPU/GPU", "中", "国产高端处理器样本，观察算力国产替代。"),
            ("603019.SH", "中科曙光", "服务器/算力平台", "中", "算力基础设施平台样本。"),
            ("000977.SZ", "浪潮信息", "服务器", "中", "服务器龙头样本，观察AI服务器需求传导。"),
            ("000938.SZ", "紫光股份", "网络/云基础设施", "低", "网络与云基础设施对照样本。"),
        ],
    )
    _register_theme(
        repository,
        _seed_theme(
            "semiconductor_equipment_materials",
            "半导体设备材料国产化",
            "制程设备、清洗、CMP、EDA和材料环节可能受益于国产化和先进封装扩散。",
            ["半导体设备", "材料", "EDA", "国产替代"],
        ),
        [
            ("002371.SZ", "北方华创", "设备平台", "中", "半导体设备平台型样本。"),
            ("688012.SH", "中微公司", "刻蚀/MOCVD", "中", "关键制程设备样本。"),
            ("688072.SH", "拓荆科技", "薄膜沉积", "中", "薄膜沉积设备样本。"),
            ("688120.SH", "华海清科", "CMP设备", "中", "CMP设备样本。"),
            ("688019.SH", "安集科技", "材料", "中", "CMP材料与湿电子化学品样本。"),
        ],
    )
    _register_theme(
        repository,
        _seed_theme(
            "power_grid_export_upgrade",
            "电网设备出海与升级",
            "全球电气化、数据中心用电和电网投资可能推动一次/二次设备长期景气。",
            ["电网", "出海", "特高压", "电力设备"],
        ),
        [
            ("000400.SZ", "许继电气", "二次设备", "中", "电网自动化和直流输电样本。"),
            ("600312.SH", "平高电气", "一次设备", "中", "高压开关和特高压设备样本。"),
            ("002028.SZ", "思源电气", "综合电力设备", "中", "电力设备出海样本。"),
            ("688676.SH", "金盘科技", "干变/储能设备", "中", "数据中心和新能源电力设备样本。"),
            ("603606.SH", "东方电缆", "海缆", "低", "海风和海缆景气对照样本。"),
        ],
    )
    _register_theme(
        repository,
        _seed_theme(
            "ai_edge_hardware",
            "AI端侧硬件",
            "端侧AI模型、智能终端和边缘计算可能带来新一轮硬件创新周期。",
            ["端侧AI", "消费电子", "边缘计算", "智能终端"],
        ),
        [
            ("688036.SH", "传音控股", "终端品牌", "中", "新兴市场智能终端和端侧AI样本。"),
            ("002475.SZ", "立讯精密", "精密制造", "中", "智能硬件制造平台样本。"),
            ("002241.SZ", "歌尔股份", "声学/XR", "低", "XR和智能硬件弹性样本。"),
            ("300496.SZ", "中科创达", "端侧软件", "中", "智能终端操作系统和边缘软件样本。"),
            ("603986.SH", "兆易创新", "存储/MCU", "低", "端侧芯片配套样本。"),
        ],
    )
    _register_theme(
        repository,
        _seed_theme(
            "innovative_drug_globalization",
            "创新药出海",
            "中国创新药研发能力和BD出海可能重塑医药长期赔率结构。",
            ["创新药", "出海", "BD", "医药"],
        ),
        [
            ("600276.SH", "恒瑞医药", "创新药平台", "中", "传统药企向创新药平台转型样本。"),
            ("688235.SH", "百济神州", "全球化平台", "中", "全球化创新药商业化样本。"),
            ("688180.SH", "君实生物", "创新药", "低", "国产创新药研发样本。"),
            ("688331.SH", "荣昌生物", "ADC/生物药", "中", "ADC和生物药出海样本。"),
            ("603259.SH", "药明康德", "CXO", "低", "创新药产业链服务对照样本。"),
        ],
    )


def _seed_theme(theme_id: str, name: str, thesis: str, tags: list[str]) -> dict[str, object]:
    return {
        "theme_id": theme_id,
        "name": name,
        "status": "observation",
        "stage": "Seed",
        "horizon_years": 10,
        "thesis_type": "emerging_power_law_candidate",
        "thesis": thesis,
        "upgrade_rule": "主题内至少3只样本出现早期起势信号，且成熟/拥挤分未明显过高。",
        "disconfirm_rule": "产业需求无法兑现，财务增长持续缺席，或主题股票普遍进入高拥挤但无业绩支撑。",
        "linked_note_id": "",
        "tags": tags,
    }


def _register_theme(repository: SystemRepository, theme: dict[str, object], stocks: list[tuple[str, str, str, str, str]]) -> None:
    repository.upsert_opportunity_theme(theme)
    for symbol, name, chain_role, conviction, thesis in stocks:
        repository.upsert_opportunity_stock(
            {
                "theme_id": str(theme["theme_id"]),
                "symbol": symbol,
                "name": name,
                "status": "candidate_seed",
                "watch_level": "B",
                "chain_role": chain_role,
                "conviction": conviction,
                "source_type": "built_in_seed",
                "source_detail": f"内置候选样本，链路角色: {chain_role}，需补充行业/概念/主营等入池证据后才进入正式观察池。",
                "verification_status": "unverified",
                "first_observed_date": "20260701",
                "thesis": thesis,
                "disconfirm_condition": "产业假设无法被收入、利润或相对强弱验证，且连续两轮监控未改善。",
            }
        )
