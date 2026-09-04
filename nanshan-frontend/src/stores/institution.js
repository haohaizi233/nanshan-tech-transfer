import { defineStore } from 'pinia'
import { ref } from 'vue'

import {
  initialInstitutions
} from '../mock/institutions'

const clone = data => {
  return JSON.parse(
    JSON.stringify(data)
  )
}

export const useInstitutionStore =
  defineStore(
    'institution',
    () => {
      const institutions = ref(
        clone(initialInstitutions)
      )

      const add = data => {
        institutions.value.unshift(
          data
        )
      }

      const update = (
        id,
        data
      ) => {
        const target =
          institutions.value.find(
            item => item.id === id
          )

        if (!target) return

        Object.assign(
          target,
          data
        )
      }

      const toggleStatus = id => {
        const target =
          institutions.value.find(
            item => item.id === id
          )

        if (!target) return

        target.status =
          target.status === '已上架'
            ? '已下架'
            : '已上架'
      }

      const remove = id => {
        institutions.value =
          institutions.value.filter(
            item => item.id !== id
          )
      }

      const batchStatus = (
        ids,
        status
      ) => {
        institutions.value.forEach(
          item => {
            if (
              ids.includes(item.id)
            ) {
              item.status = status
            }
          }
        )
      }

      const batchRemove = ids => {
        institutions.value =
          institutions.value.filter(
            item =>
              !ids.includes(item.id)
          )
      }

      return {
        institutions,
        add,
        update,
        toggleStatus,
        remove,
        batchStatus,
        batchRemove
      }
    }
  )