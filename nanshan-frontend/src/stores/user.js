import { defineStore } from 'pinia'
import { ref } from 'vue'

import {
  initialUsers
} from '../mock/users'

const clone = data =>
  JSON.parse(
    JSON.stringify(data)
  )

export const useUserStore =
  defineStore(
    'user',
    () => {
      const users =
        ref(
          clone(initialUsers)
        )

      const getById = id =>
        users.value.find(
          item =>
            item.id === id
        )

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

      const toggleStatus =
        id => {
          const item =
            getById(id)

          if (!item) return

          item.status =
            item.status ===
            '禁用'
              ? '正常'
              : '禁用'
        }

      const approve = id => {
        const item =
          getById(id)

        if (!item) return

        item.status =
          '正常'
      }

      return {
        users,
        getById,
        update,
        toggleStatus,
        approve
      }
    }
  )