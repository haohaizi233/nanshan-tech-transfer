export const cooperationTypes = [
  '技术合作',
  '项目合作',
  '联合研发',
  '成果转化',
  '技术咨询',
]

export const cooperationStatuses = [
  '待处理',
  '已接受',
  '已确认',
  '已完成',
  '已归档',
  '已拒绝',
]

const mainCooperation = {
  id: 'CP202405220012',

  initiator: '深圳先进技术研究院',

  initiatorType: '机构',

  contactName: '张明',

  phone: '136 8888 1234',

  email: 'zhangming@siat.ac.cn',

  target: '华为技术有限公司',

  targetType: '企业',

  type: '技术合作',

  submittedAt: '2024-05-22 14:32:18',

  status: '待处理',

  request:
    '我院在智能传感器与边缘计算领域拥有多项核心技术，希望与贵公司在工业物联网场景开展联合研发，共同推进技术落地与产品化，探索市场化合作模式。',

  message:
    '期待与贵公司建立长期合作关系，共同推动行业发展。',

  specialist: '',

  communications: [
    {
      id: 1,

      user: '张明',

      organization: '深圳先进技术研究院',

      role: '发起人',

      content:
        '补充资料：已上传技术方案简介及相关专利清单，请查收。',

      time: '2024-05-22 14:36:52',

      attachments: [
        '技术方案简介.pdf',
        '相关专利清单.xlsx',
      ],
    },

    {
      id: 2,

      user: '管理员',

      organization: '系统',

      role: '系统',

      content:
        '已分配对接专员：李晓明（南山科技创新局）',

      time: '2024-05-22 15:08:41',

      attachments: [],
    },

    {
      id: 3,

      user: '李晓明',

      organization: '南山科技创新局',

      role: '对接专员',

      content:
        '已与双方沟通对接安排，拟定 5 月 24 日上午进行线上会议。',

      time: '2024-05-23 09:18:33',

      attachments: [],
    },
  ],

  history: [
    {
      id: 1,
      status: '待处理',
      description: '意向已提交，等待管理员处理',
      time: '2024-05-22 14:32:18',
      operator: '提交人：张明',
    },
  ],
}

const companies = [
  '华为技术有限公司',
  '深圳智造科技有限公司',
  '南山人工智能产业中心',
  '深圳新能源科技集团',
]

const institutions = [
  '深圳先进技术研究院',
  '南方科技大学研究院',
  '深圳市科技创新服务中心',
  '南山先进材料研究院',
]

const generatedCooperations = Array.from(
  { length: 32 },
  (_, index) => {
    const number = index + 13

    const status = [
      '待处理',
      '已接受',
      '已确认',
      '已完成',
      '已归档',
    ][index % 5]

    return {
      id: `CP202405${String(number).padStart(6, '0')}`,

      initiator:
        institutions[index % institutions.length],

      initiatorType: '机构',

      contactName:
        ['张伟', '李娜', '王明', '刘洋'][index % 4],

      phone: '138 0013 8000',

      email: 'contact@example.com',

      target:
        companies[index % companies.length],

      targetType: '企业',

      type:
        cooperationTypes[
          index % cooperationTypes.length
        ],

      submittedAt:
        `2024-05-${String(
          Math.max(1, 21 - (index % 18))
        ).padStart(2, '0')} 10:30:00`,

      status,

      request:
        `希望围绕科技项目 ${number} 开展技术合作及产业化对接。`,

      message:
        '希望建立长期合作关系。',

      specialist:
        status === '待处理'
          ? ''
          : '李晓明',

      communications: [],

      history: [],
    }
  }
)

export const initialCooperations = [
  mainCooperation,
  ...generatedCooperations,
]