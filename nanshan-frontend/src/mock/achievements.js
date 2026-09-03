const firstPageData = [
  {
    id: 'ACH20250522001',
    name: '高性能碳纤维复合材料制备技术',
    category: '新材料',
    organization: '南山先进材料研究院',
    publisher: '张伟',
    status: '已发布',
    auditStatus: '已通过',
    views: 1258,
    favorites: 86,
    createdAt: '2025-05-22 14:30',
    description: '面向高性能复合材料领域的新型碳纤维制备及应用技术。',
  },
  {
    id: 'ACH20250521008',
    name: '基于AI的工业缺陷检测系统',
    category: '人工智能',
    organization: '深圳智造科技有限公司',
    publisher: '李娜',
    status: '已发布',
    auditStatus: '已通过',
    views: 986,
    favorites: 64,
    createdAt: '2025-05-21 10:15',
    description: '通过机器视觉与人工智能算法完成工业产品缺陷自动检测。',
  },
  {
    id: 'ACH20250520015',
    name: '新一代高能量密度固态电池技术',
    category: '新能源',
    organization: '南科大能源研究院',
    publisher: '王磊',
    status: '审核中',
    auditStatus: '待审核',
    views: 512,
    favorites: 32,
    createdAt: '2025-05-20 16:45',
    description: '面向新能源汽车和储能领域的新型固态电池技术。',
  },
  {
    id: 'ACH20250519023',
    name: '生物医用可降解高分子材料',
    category: '生物医药',
    organization: '深圳湾生物材料团队',
    publisher: '陈晨',
    status: '已发布',
    auditStatus: '已通过',
    views: 765,
    favorites: 58,
    createdAt: '2025-05-19 09:20',
    description: '可应用于组织工程和医疗器械领域的可降解高分子材料。',
  },
  {
    id: 'ACH20250518005',
    name: '智能光伏运维监测平台',
    category: '智能制造',
    organization: '绿能数智科技（深圳）',
    publisher: '刘洋',
    status: '已下架',
    auditStatus: '已通过',
    views: 432,
    favorites: 21,
    createdAt: '2025-05-18 11:05',
    description: '面向光伏电站的智能化设备监测和故障预警平台。',
  },
  {
    id: 'ACH20250517012',
    name: '城市内涝智能预警与调度系统',
    category: '信息技术',
    organization: '深港城市大数据实验室',
    publisher: '赵敏',
    status: '已发布',
    auditStatus: '已通过',
    views: 1103,
    favorites: 75,
    createdAt: '2025-05-17 15:40',
    description: '基于城市实时数据的内涝风险分析与调度系统。',
  },
  {
    id: 'ACH20250516009',
    name: '高精度激光雷达感知算法',
    category: '人工智能',
    organization: '南山智能感知团队',
    publisher: '周强',
    status: '审核中',
    auditStatus: '待审核',
    views: 328,
    favorites: 18,
    createdAt: '2025-05-16 13:30',
    description: '服务于自动驾驶与机器人应用的高精度环境感知算法。',
  },
  {
    id: 'ACH20250515003',
    name: '新型抗菌涂层材料及应用',
    category: '新材料',
    organization: '深圳新材创新中心',
    publisher: '吴迪',
    status: '已下架',
    auditStatus: '已驳回',
    views: 197,
    favorites: 9,
    createdAt: '2025-05-15 10:00',
    description: '适用于医疗器械及公共设施的新型长效抗菌涂层。',
  },
]

// 再生成一些数据，方便真正测试分页
const categories = [
  '新材料',
  '人工智能',
  '新能源',
  '生物医药',
  '智能制造',
  '信息技术',
]

const organizations = [
  '南山先进材料研究院',
  '深圳科技创新中心',
  '南科大联合实验室',
  '深圳智能制造研究院',
]

const statuses = ['已发布', '审核中', '已下架']
const auditStatuses = ['已通过', '待审核', '已驳回']

const generatedData = Array.from({ length: 120 }, (_, index) => {
  const number = index + 9
  const day = Math.max(1, 15 - (index % 14))

  return {
    id: `ACH2025${String(number).padStart(7, '0')}`,
    name: `科技成果示例项目 ${number}`,
    category: categories[index % categories.length],
    organization: organizations[index % organizations.length],
    publisher: ['张伟', '李娜', '王磊', '陈晨'][index % 4],
    status: statuses[index % statuses.length],
    auditStatus: auditStatuses[index % auditStatuses.length],
    views: 100 + index * 17,
    favorites: 5 + (index % 90),
    createdAt: `2025-05-${String(day).padStart(2, '0')} 10:30`,
    description: `这是科技成果示例项目 ${number} 的成果简介。`,
  }
})

export const initialAchievements = [
  ...firstPageData,
  ...generatedData,
]

export const achievementCategories = [
  '新材料',
  '人工智能',
  '新能源',
  '生物医药',
  '智能制造',
  '信息技术',
]

export const achievementStatuses = [
  '已发布',
  '审核中',
  '已下架',
]

export const achievementAuditStatuses  = [
  '已通过',
  '待审核',
  '已驳回',
]