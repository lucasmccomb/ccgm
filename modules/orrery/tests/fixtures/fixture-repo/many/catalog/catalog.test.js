const m = require('./index')
if (m.feature !== 'catalog') throw new Error('fixture self-check')
