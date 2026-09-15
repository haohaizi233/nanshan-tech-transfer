export const PATENT_DETAIL_NAV_ITEMS = [
  {
    key: 'abstract',
    label: '摘要',
    icon: '/static/icons/patent-detail/abstract.png',
    activeIcon: '/static/icons/patent-detail/abstract-active.png',
  },
  {
    key: 'claims',
    label: '权利要求',
    icon: '/static/icons/patent-detail/claims.png',
    activeIcon: '/static/icons/patent-detail/claims-active.png',
  },
  {
    key: 'description',
    label: '说明书',
    icon: '/static/icons/patent-detail/description.png',
    activeIcon: '/static/icons/patent-detail/description-active.png',
  },
]

export function resolvePatentDetailSection(section) {
  return PATENT_DETAIL_NAV_ITEMS.some(item => item.key === section)
    ? section
    : PATENT_DETAIL_NAV_ITEMS[0].key
}

export function getPatentDetailNavigationTarget(section) {
  return { section: resolvePatentDetailSection(section) }
}
