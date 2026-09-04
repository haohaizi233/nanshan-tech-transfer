export const userTypes = [
  '企业用户',
  '科研人员',
  '机构用户'
]

export const userStatuses = [
  '正常',
  '待审',
  '禁用'
]

const baseUsers = [
  {
    id: '10000001',
    username: '张三',
    type: '企业用户',
    phone: '138****1234',
    organization: '深圳市智创科技有限公司',
    status: '正常',
    registeredAt: '2024-05-16 09:21:33',
    lastLogin: '2024-05-22 14:32:18'
  },
  {
    id: '10000002',
    username: '李四',
    type: '科研人员',
    phone: '139****5678',
    organization: '深圳大学材料学院',
    status: '正常',
    registeredAt: '2024-05-15 16:45:12',
    lastLogin: '2024-05-21 10:15:09'
  },
  {
    id: '10000003',
    username: '王五',
    type: '机构用户',
    phone: '137****2468',
    organization: '南山区科技创新局',
    status: '正常',
    registeredAt: '2024-05-14 11:02:07',
    lastLogin: '2024-05-22 09:08:31'
  },
  {
    id: '10000004',
    username: '赵六',
    type: '企业用户',
    phone: '186****8888',
    organization: '深圳云智造技术有限公司',
    status: '待审',
    registeredAt: '2024-05-13 08:33:55',
    lastLogin: ''
  },
  {
    id: '10000005',
    username: '孙七',
    type: '科研人员',
    phone: '188****1357',
    organization: '香港中文大学（深圳）',
    status: '正常',
    registeredAt: '2024-05-12 14:20:41',
    lastLogin: '2024-05-20 17:50:22'
  },
  {
    id: '10000006',
    username: '周八',
    type: '企业用户',
    phone: '159****9753',
    organization: '深圳市新材料未来有限公司',
    status: '禁用',
    registeredAt: '2024-05-11 10:11:23',
    lastLogin: '2024-05-18 09:44:05'
  },
  {
    id: '10000007',
    username: '吴九',
    type: '机构用户',
    phone: '177****2468',
    organization: '深圳市南山技术转移中心',
    status: '正常',
    registeredAt: '2024-05-10 09:05:18',
    lastLogin: '2024-05-22 11:27:36'
  },
  {
    id: '10000008',
    username: '郑十',
    type: '科研人员',
    phone: '150****8642',
    organization: '北京大学深圳研究生院',
    status: '待审',
    registeredAt: '2024-05-09 15:30:56',
    lastLogin: ''
  }
]

const generatedUsers =
  Array.from(
    { length: 92 },
    (_, index) => ({
      id:
        String(
          10000009 +
          index
        ),

      username:
        `测试用户${index + 1}`,

      type:
        userTypes[
          index %
          userTypes.length
        ],

      phone:
        `13${index % 10}****${String(
          2000 + index
        ).slice(-4)}`,

      organization:
        `南山科技企业 ${index + 1}`,

      status:
        [
          '正常',
          '正常',
          '正常',
          '待审',
          '禁用'
        ][index % 5],

      registeredAt:
        `2024-05-${String(
          Math.max(
            1,
            8 - (index % 7)
          )
        ).padStart(2, '0')} 10:20:00`,

      lastLogin:
        index % 4 === 0
          ? ''
          : '2024-05-22 10:20:00'
    })
  )

export const initialUsers = [
  ...baseUsers,
  ...generatedUsers
]