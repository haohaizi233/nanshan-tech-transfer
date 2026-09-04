import {
  defineStore
} from 'pinia'

import {
  ref
} from 'vue'

import {
  initialRequirements
} from '../mock/requirements'

const cloneData = data => {
  return JSON.parse(
    JSON.stringify(data)
  )
}

export const useRequirementStore =
  defineStore(
    'requirement',
    () => {
      const requirements =
        ref(
          cloneData(
            initialRequirements
          )
        )

      const getById = id => {
        return requirements.value.find(
          item => item.id === id
        )
      }

      const updateRequirement = (
        id,
        data
      ) => {
        const item = getById(id)

        if (!item) return

        Object.assign(
          item,
          data
        )
      }

      const approve = id => {
        const item = getById(id)

        if (!item) return

        item.auditStatus =
          '已通过'

        item.status =
          '已发布'

        item.auditRecords.push({
          id: Date.now(),
          action: '审核通过',
          operator: '管理员',
          time: new Date()
            .toLocaleString(),
          remark:
            '管理员审核通过，该需求可以正式发布',
        })
      }

      const reject = id => {
        const item = getById(id)

        if (!item) return

        item.auditStatus =
          '已驳回'

        item.status =
          '已驳回'

        item.auditRecords.push({
          id: Date.now(),
          action: '审核驳回',
          operator: '管理员',
          time: new Date()
            .toLocaleString(),
          remark:
            '管理员审核驳回该需求',
        })
      }

      const toggleFavorite = id => {
        const item = getById(id)

        if (!item) return

        item.favorite =
          !item.favorite
      }

      const togglePublish = id => {
        const item = getById(id)

        if (!item) return

        if (
          item.status ===
          '已发布'
        ) {
          item.status = '已关闭'
        } else {
          item.status = '已发布'
        }
      }

      return {
        requirements,
        getById,
        updateRequirement,
        approve,
        reject,
        toggleFavorite,
        togglePublish,
      }
    }
  )