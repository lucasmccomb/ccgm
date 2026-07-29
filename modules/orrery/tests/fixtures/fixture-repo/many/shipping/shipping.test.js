const m = require('./index')
if (m.feature !== 'shipping') throw new Error('fixture self-check')
