import { fetchProducts } from '../lib/api'
export function ProductGrid() {
  const el = document.createElement('div')
  el.className = 'grid'
  fetchProducts().then((items) => (el.textContent = String(items.length)))
  return el
}
