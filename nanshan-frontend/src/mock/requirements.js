export const requirementIndustries = [
  '智能制造',
  '人工智能',
  '新能源',
  '新材料',
  '生物医药',
  '信息技术',
]

export const requirementStatuses = [
  '审核中',
  '已发布',
  '对接中',
  '已完成',
  '已关闭',
  '已驳回',
]

const mainRequirement = {
  id: 'REQ202505210001',
  title: '寻求工业机器人集成解决方案',

  organization: '深圳智造科技有限公司',
  certified: true,

  industry: '智能制造 > 工业自动化',

  publishedAt: '2025-05-21 10:30',

  budget: '80万-150万元',

  cooperation: '技术合作、项目合作',

  status: '审核中',
  auditStatus: '待审核',

  views: 128,

  favorite: false,

  summary:
    '我司计划在现有产线中引入工业机器人系统，用于提升产线自动化水平，降低人工成本，提高生产效率与产品一致性。现寻求具备丰富项目经验的集成商，提供完整的机器人集成解决方案，包含方案设计、设备选型、系统集成、调试及售后服务。',

  requirements: [
    '基于我司现有产线工艺，提供机器人应用工位设计及整体集成方案',
    '完成机器人系统集成，包括机械、电气、视觉、夹具等配套设计与实施',
    '提供人员培训、试运行、验收以及后续维护支持服务',
  ],

  indicators: [
    '适用场景：上下料、焊接、装配、码垛等',
    '节拍要求：≤ 12s/件',
    '负载要求：≥ 10kg',
    '重复定位精度：≤ ±0.05mm',
    '系统兼容：支持与现有 MES / PLC 系统对接',
    '安全标准：符合 GB 11291.1-2023 等相关国家标准',
  ],

  contact: {
    name: '张伟',
    phone: '138 0013 8000',
    email: 'zhangwei@zz-tech.com',
    address: '深圳市南山区科技园科发路1号智造大厦B座12层',
  },

  attachments: [
    {
      id: 1,
      name: '产线工艺说明书.pdf',
      size: '2.34 MB',
      uploadedAt: '2025-05-21 10:31',
      uploader: '张伟',
    },
  ],

  auditRecords: [
    {
      id: 1,
      action: '提交需求',
      operator: '张伟',
      time: '2025-05-21 10:30',
      remark: '用户提交需求，等待平台审核',
    },
    {
      id: 2,
      action: '受理需求',
      operator: '管理员',
      time: '2025-05-21 11:05',
      remark: '需求已进入审核流程',
    },
  ],

  dockingRecords: [],
}

const generatedRequirements = Array.from(
  { length: 35 },
  (_, index) => {
    const number = index + 2
    const industry =
      requirementIndustries[
        index % requirementIndustries.length
      ]

    const statusList = [
      '已发布',
      '对接中',
      '已完成',
      '审核中',
      '已关闭',
    ]

    return {
      id: `REQ202505${String(number).padStart(6, '0')}`,

      title: [
        '智能制造产线升级解决方案需求',
        '机器视觉质量检测技术需求',
        '新能源储能系统优化需求',
        '高性能复合材料研发合作需求',
        '工业数据智能分析平台需求',
        '机器人柔性装配解决方案需求',
      ][index % 6],

      organization: [
        '深圳智能制造有限公司',
        '南山科技发展有限公司',
        '深圳新能源产业研究院',
        '深港智能产业中心',
      ][index % 4],

      certified: index % 3 !== 0,

      industry,

      publishedAt:
        `2025-05-${String(
          Math.max(1, 20 - (index % 18))
        ).padStart(2, '0')} 10:30`,

      budget: [
        '30万-50万元',
        '50万-100万元',
        '80万-150万元',
        '100万-300万元',
      ][index % 4],

      cooperation: [
        '技术合作',
        '项目合作',
        '联合研发',
        '成果转化',
      ][index % 4],

      status:
        statusList[index % statusList.length],

      auditStatus:
        index % 4 === 3
          ? '待审核'
          : '已通过',

      views: 80 + index * 21,

      favorite: false,

      summary: `这是第 ${number} 条科技需求的需求概述。`,

      requirements: [
        '提供完整的技术解决方案',
        '完成项目实施与系统集成',
        '提供技术培训及后续支持',
      ],

      indicators: [
        '满足相关国家和行业标准',
        '支持现有业务系统对接',
        '具备稳定运行和扩展能力',
      ],

      contact: {
        name: ['张伟', '李娜', '王磊'][index % 3],
        phone: '138 0013 8000',
        email: 'contact@example.com',
        address: '深圳市南山区科技园',
      },

      attachments: [],

      auditRecords: [],

      dockingRecords: [],
    }
  }
)

export const initialRequirements = [
  mainRequirement,
  ...generatedRequirements,
]