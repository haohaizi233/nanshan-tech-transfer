export const statistics = [
  {
    key: 'users',
    label: '用户总数',
    value: '12,842',
    change: '8.21%',
    trend: 'up',
    icon: 'user',
    color: 'blue'
  },
  {
    key: 'achievements',
    label: '成果总数',
    value: '3,256',
    change: '6.35%',
    trend: 'up',
    icon: 'achievement',
    color: 'green'
  },
  {
    key: 'requirements',
    label: '需求总数',
    value: '2,187',
    change: '5.12%',
    trend: 'up',
    icon: 'requirement',
    color: 'orange'
  },
  {
    key: 'cooperation',
    label: '合作对接',
    value: '1,278',
    change: '12.45%',
    trend: 'up',
    icon: 'cooperation',
    color: 'purple'
  },
  {
    key: 'pending',
    label: '待审核',
    value: '356',
    change: '3.67%',
    trend: 'down',
    icon: 'pending',
    color: 'yellow'
  }
]

export const trendMap = {
  7: {
    labels: [
      '05-16',
      '05-17',
      '05-18',
      '05-19',
      '05-20',
      '05-21',
      '05-22'
    ],
    users: [280, 350, 330, 405, 395, 375, 395],
    achievements: [170, 220, 190, 280, 245, 245, 286],
    requirements: [85, 120, 105, 150, 120, 155, 182]
  },

  30: {
    labels: [
      '04-23',
      '04-28',
      '05-03',
      '05-08',
      '05-13',
      '05-18',
      '05-22'
    ],
    users: [240, 290, 320, 350, 330, 380, 428],
    achievements: [150, 180, 210, 225, 235, 260, 286],
    requirements: [70, 85, 105, 120, 135, 160, 182]
  },

  90: {
    labels: [
      '02月',
      '03月',
      '03月底',
      '04月',
      '04月底',
      '05月',
      '当前'
    ],
    users: [180, 220, 270, 310, 350, 390, 428],
    achievements: [100, 130, 170, 190, 225, 260, 286],
    requirements: [50, 70, 90, 110, 135, 160, 182]
  }
}

export const achievementStatus = [
  {
    name: '已发布',
    value: 1285,
    percent: '39.45%',
    color: '#2a80f5'
  },
  {
    name: '审核中',
    value: 632,
    percent: '19.40%',
    color: '#28c6a4'
  },
  {
    name: '已下架',
    value: 278,
    percent: '8.54%',
    color: '#f6aa2c'
  },
  {
    name: '已转化',
    value: 789,
    percent: '24.22%',
    color: '#70d59a'
  },
  {
    name: '草稿',
    value: 272,
    percent: '8.39%',
    color: '#e3e6ec'
  }
]

export const requirementStatus = [
  {
    name: '已发布',
    value: 962,
    percent: '44.00%',
    color: '#2a80f5'
  },
  {
    name: '对接中',
    value: 545,
    percent: '24.93%',
    color: '#21c3a0'
  },
  {
    name: '已完成',
    value: 332,
    percent: '15.19%',
    color: '#55ca87'
  },
  {
    name: '已关闭',
    value: 207,
    percent: '9.47%',
    color: '#f4c63c'
  },
  {
    name: '草稿',
    value: 141,
    percent: '6.45%',
    color: '#e5e7ed'
  }
]

export const todoList = [
  {
    id: 1,
    type: 'achievement',
    text: '成果《高性能碳纤维复合材料关键技术》等待审核',
    tag: '成果审核',
    tagClass: 'blue',
    iconClass: 'blue',
    time: '10分钟前',
    route: '/admin/achievements'
  },
  {
    id: 2,
    type: 'requirement',
    text: '需求《智能制造产线升级解决方案需求》等待审核',
    tag: '需求审核',
    tagClass: 'green',
    iconClass: 'green',
    time: '25分钟前',
    route: '/admin/requirements'
  },
  {
    id: 3,
    type: 'cooperation',
    text: '合作对接《深圳先进院某科技企业合作对接》待处理',
    tag: '对接处理',
    tagClass: 'purple',
    iconClass: 'purple',
    time: '1小时前',
    route: '/admin/cooperation'
  },
  {
    id: 4,
    type: 'institution',
    text: '机构《深圳市创新技术研究院》资料待审核',
    tag: '机构审核',
    tagClass: 'orange',
    iconClass: 'orange',
    time: '2小时前',
    route: '/admin/institutions'
  },
  {
    id: 5,
    type: 'user',
    text: '用户《李明（企业用户）》申请注册等待审核',
    tag: '用户审核',
    tagClass: 'red',
    iconClass: 'red',
    time: '3小时前',
    route: '/admin/users'
  }
]

export const activityList = [
  {
    id: 1,
    color: '#31bf7a',
    text: '用户“华为技术有限公司”发布了新需求《面向工业互联网的边缘计算平台需求》',
    time: '10分钟前'
  },
  {
    id: 2,
    color: '#2f80f7',
    text: '成果《一种高效节能的电机驱动控制方法》已通过审核并发布',
    time: '35分钟前'
  },
  {
    id: 3,
    color: '#f6a623',
    text: '机构“深圳市人工智能与机器人研究院”更新了机构资料',
    time: '1小时前'
  },
  {
    id: 4,
    color: '#8469ee',
    text: '系统管理员完成了用户“张伟（企业用户）”的审核',
    time: '2小时前'
  },
  {
    id: 5,
    color: '#f25b65',
    text: '合作对接《清华大学深圳研究院某科技企业合作意向》匹配成功',
    time: '3小时前'
  }
]