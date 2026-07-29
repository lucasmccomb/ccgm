const BASE = import.meta.env.API_BASE_URL || '/api'
export function fetchProducts() { return fetch(BASE + '/products').then((r) => r.json()) }
export function postCheckout(cart) {
  return fetch(BASE + '/checkout', { method: 'POST', body: JSON.stringify(cart) })
}
