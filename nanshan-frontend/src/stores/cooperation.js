import {
  defineStore
} from 'pinia'

import {
  ref
} from 'vue'

import {
  initialCooperations
} from '../mock/cooperations'

const cloneData = data => {
  return JSON.parse(
    JSON.stringify(data)
  )
}

const getNow = () => {
  return new Date()
    .toLocaleString(
      'zh-CN',
      {
        hour12: false
      }
    )
}

export const useCooperationStore =
  defineStore(
    'cooperation',
    () => {
      const cooperations =
        ref(
          cloneData(
            initialCooperations
          )
        )

      const getById = id => {
        return cooperations.value.find(
          item =>
            item.id === id
        )
      }

      const update = (
        id,
        data
      ) => {
        const item =
          getById(id)

        if (!item) return

        Object.assign(
          item,
          data
        )
      }

      const addHistory = (
        item,
        status,
        description,
        operator
      ) => {
        item.history.push({
          id: Date.now(),

          status,

          description,

          time: getNow(),

          operator,
        })
      }

      const accept = id => {
        const item =
          getById(id)

        if (!item) return

        item.status =
          '已接受'

        item.specialist =
          '李晓明'

        addHistory(
          item,
          '已接受',
          '已由管理员接受意向',
          '操作人：管理员'
        )

        item.communications.push({
          id: Date.now(),

          user: '管理员',

          organization: '系统',

          role: '系统',

          content:
            '管理员已接受合作意向，并分配对接专员：李晓明。',

          time: getNow(),

          attachments: [],
        })
      }

      const reject = id => {
        const item =
          getById(id)

        if (!item) return

        item.status =
          '已拒绝'

        addHistory(
          item,
          '已拒绝',
          '管理员拒绝该合作意向',
          '操作人：管理员'
        )
      }

      const confirm = id => {
        const item =
          getById(id)

        if (!item) return

        item.status =
          '已确认'

        addHistory(
          item,
          '已确认',
          '双方已确认对接安排',
          '操作人：李晓明'
        )
      }

      const complete = id => {
        const item =
          getById(id)

        if (!item) return

        item.status =
          '已完成'

        addHistory(
          item,
          '已完成',
          '合作对接已完成',
          '操作人：李晓明'
        )
      }

      const archive = id => {
        const item =
          getById(id)

        if (!item) return

        item.status =
          '已归档'

        addHistory(
          item,
          '已归档',
          '合作意向已归档',
          '操作人：管理员'
        )
      }

      const addCommunication = (
        id,
        content
      ) => {
        const item =
          getById(id)

        if (!item) return

        item.communications.push({
          id: Date.now(),

          user: '管理员',

          organization:
            '南山科转通',

          role: '管理员',

          content,

          time: getNow(),

          attachments: [],
        })
      }

      return {
        cooperations,

        getById,

        update,

        accept,

        reject,

        confirm,

        complete,

        archive,

        addCommunication,
      }
    }
  )