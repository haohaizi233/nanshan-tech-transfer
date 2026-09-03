export const institutionTypes = [
  '投资机构',
  '服务机构',
  '银行',
  '高校',
  '研究院'
]

export const institutionStatuses = [
  '已上架',
  '已下架'
]

const baseInstitutions = [
  {
    id: '10001',
    name: '深高新投集团有限公司',
    type: '投资机构',
    contact: '张伟',
    phone: '138****1234',
    region: '广东省 深圳市 南山区',
    status: '已上架',
    createdAt: '2024-05-22 10:30:45'
  },
  {
    id: '10002',
    name: '深圳市科技创新服务中心',
    type: '服务机构',
    contact: '李娜',
    phone: '139****5678',
    region: '广东省 深圳市 福田区',
    status: '已上架',
    createdAt: '2024-05-21 16:20:30'
  },
  {
    id: '10003',
    name: '中国建设银行股份有限公司深圳南山支行',
    type: '银行',
    contact: '王强',
    phone: '137****9012',
    region: '广东省 深圳市 南山区',
    status: '已上架',
    createdAt: '2024-05-20 09:15:12'
  },
  {
    id: '10004',
    name: '香港科技大学（深圳）',
    type: '高校',
    contact: '陈教授',
    phone: '136****3456',
    region: '广东省 深圳市 南山区',
    status: '已上架',
    createdAt: '2024-05-19 14:05:33'
  },
  {
    id: '10005',
    name: '深圳先进技术研究院',
    type: '研究院',
    contact: '刘博士',
    phone: '135****7890',
    region: '广东省 深圳市 南山区',
    status: '已下架',
    createdAt: '2024-05-18 11:23:44'
  },
  {
    id: '10006',
    name: '招商局资本管理有限责任公司',
    type: '投资机构',
    contact: '赵磊',
    phone: '134****5678',
    region: '广东省 深圳市 南山区',
    status: '已上架',
    createdAt: '2024-05-17 15:40:21'
  },
  {
    id: '10007',
    name: '微众银行科技金融部',
    type: '银行',
    contact: '孙悦',
    phone: '133****2468',
    region: '广东省 深圳市 前海深港合作区',
    status: '已上架',
    createdAt: '2024-05-16 10:12:08'
  }
]

const generatedInstitutions = Array.from(
  { length: 43 },
  (_, index) => ({
    id: String(10008 + index),

    name: `南山科技服务机构 ${index + 1}`,

    type:
      institutionTypes[
        index % institutionTypes.length
      ],

    contact:
      ['张伟', '李娜', '王强', '陈明'][
        index % 4
      ],

    phone:
      `13${index % 10}****${String(
        1000 + index
      ).slice(-4)}`,

    region:
      '广东省 深圳市 南山区',

    status:
      index % 6 === 0
        ? '已下架'
        : '已上架',

    createdAt:
      `2024-05-${String(
        Math.max(1, 15 - (index % 14))
      ).padStart(2, '0')} 10:30:00`
  })
)

export const initialInstitutions = [
  ...baseInstitutions,
  ...generatedInstitutions
]