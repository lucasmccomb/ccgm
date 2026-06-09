# Code Quality Audit Patterns

Reference patterns for the code quality audit agent. Based on SonarQube rules, Martin Fowler's refactoring patterns, and common code smells.

## 1. Bloaters

### Long Methods
- **Threshold**: >50 lines
- **Why it matters**: Hard to understand, test, and maintain
- **Look for**: Methods that do multiple things, deeply nested logic

### Large Classes/Files
- **Threshold**: >500 lines for files, >300 lines for classes
- **Why it matters**: Violates Single Responsibility Principle
- **Look for**: Files with many unrelated functions, classes with many methods

### Long Parameter Lists
- **Threshold**: >4 parameters
- **Why it matters**: Hard to use correctly, often indicates missing abstraction
- **Pattern**:
```javascript
// Bad
function createUser(name, email, age, address, phone, role, dept, manager) {}

// Better
function createUser(userDetails: UserCreationParams) {}
```

### Primitive Obsession
- Using primitives instead of small objects
- **Pattern**:
```javascript
// Bad
function setPrice(price: number, currency: string) {}

// Better
function setPrice(money: Money) {}
```

## 2. Object-Orientation Abusers

### Switch Statements (Excessive)
- Multiple switches on the same type
- Should often be polymorphism
- **Pattern**:
```javascript
// Bad - repeated switch on type
switch (animal.type) {
  case 'dog': return 'bark'
  case 'cat': return 'meow'
}

// Better - polymorphism
animal.speak()
```

### Parallel Inheritance Hierarchies
- Creating a subclass in one hierarchy requires creating one in another

### Refused Bequest
- Subclass doesn't use inherited methods/properties

## 3. Change Preventers

### Divergent Change
- One class is commonly changed for different reasons
- **Indicator**: Class modified in many unrelated PRs

### Shotgun Surgery
- Single change requires modifying many classes
- **Indicator**: Simple feature touches 10+ files

### Feature Envy
- Method uses another class's data more than its own
- **Pattern**:
```javascript
// Bad - envies Customer
function calculateDiscount(customer) {
  return customer.orders.length > 10
    ? customer.totalSpent * 0.1
    : customer.totalSpent * 0.05
}

// Better - move to Customer class
customer.calculateDiscount()
```

## 4. Dispensables

### Dead Code
- Code that's never executed
- **Look for**:
  - Unreachable code after return/throw
  - Unused variables and parameters
  - Commented-out code blocks
  - Unused exports (no imports found)
  - Unused functions/methods
  - Feature flags that are always on/off

### Speculative Generality
- Unused abstraction "for future use"
- **Indicators**: Unused interfaces, abstract classes with one implementation

### Duplicate Code
- Same code structure in multiple places
- **Threshold**: >10 lines of similar code
- **Pattern**:
```javascript
// Bad - duplicated validation
function createUser(data) {
  if (!data.email || !data.email.includes('@')) throw Error('Invalid email')
  // ...
}
function updateUser(data) {
  if (!data.email || !data.email.includes('@')) throw Error('Invalid email')
  // ...
}

// Better - extracted
function validateEmail(email) {
  if (!email || !email.includes('@')) throw Error('Invalid email')
}
```

## 5. Couplers

### Inappropriate Intimacy
- Classes that know too much about each other's internals
- **Pattern**: Accessing private fields, knowing internal implementation

### Message Chains
- Long chains of method calls
- **Pattern**: `a.getB().getC().getD().doSomething()`
- **Better**: Law of Demeter - `a.doSomething()`

### Middle Man
- Class that only delegates to another class
- **Indicator**: Most methods just call another object's method

## 6. Complexity Issues

### High Cyclomatic Complexity
- Too many decision points
- **Threshold**: >10 per function
- **Calculation**: 1 + number of (if, else if, for, while, case, &&, ||, ?)

### High Cognitive Complexity
- Code that's hard to understand
- **Factors**:
  - Deep nesting (each level adds complexity)
  - Multiple conditions in one statement
  - Breaks in linear flow (early returns, continues)
- **Threshold**: >15 per function

### Deeply Nested Code
- **Threshold**: >4 levels of nesting
- **Pattern**:
```javascript
// Bad
if (a) {
  if (b) {
    for (x of items) {
      if (c) {
        if (d) {  // Too deep!
        }
      }
    }
  }
}

// Better - early returns, extraction
if (!a || !b) return
for (x of items) {
  if (!c || !d) continue
  // ...
}
```

## 7. Error Handling Issues

### Empty Catch Blocks
```javascript
// Bad - swallowing errors
try {
  doSomething()
} catch (e) {}

// Better - at minimum, log
try {
  doSomething()
} catch (e) {
  console.error('Failed to do something:', e)
}
```

### Catching Generic Errors
```javascript
// Bad - catches everything
try {
  await fetchData()
} catch (e) {
  return null  // What went wrong?
}

// Better - specific handling
try {
  await fetchData()
} catch (e) {
  if (e instanceof NetworkError) {
    // retry logic
  }
  throw e  // re-throw unexpected errors
}
```

### Missing Error Boundaries (React)
- Components that can throw without a boundary above them
- Critical sections: data fetching, third-party components

## 8. Naming Issues

### Inconsistent Naming
- Mixed conventions: `getUserData`, `fetch_user_info`, `loadUserProfile`
- **Expected**: Consistent casing and verb usage

### Non-Descriptive Names
- Single letters: `x`, `d`, `temp`
- Generic names: `data`, `info`, `item`, `stuff`
- **Exceptions**: Loop indices (`i`, `j`), coordinates (`x`, `y`)

### Magic Numbers/Strings
```javascript
// Bad
if (status === 3) {}
setTimeout(callback, 86400000)

// Better
const STATUS_COMPLETED = 3
const ONE_DAY_MS = 24 * 60 * 60 * 1000
```

## Severity Guidelines

| Severity | Criteria |
|----------|----------|
| **Critical** | N/A for code quality (use High for worst) |
| **High** | Dead code in critical paths, severe duplication, complexity >20 |
| **Medium** | Long methods, large files, moderate complexity |
| **Low** | Naming issues, minor code smells, style inconsistencies |
