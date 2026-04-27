---
name: code-performance
description: "Analyze code performance, profile execution time, memory usage, and generate optimization insights with data engineering modules."
metadata: {"nanobot":{"emoji":"⚡","requires":{"bins":[]}}}
---

# Code Performance Analysis

Analyze and optimize code performance across multiple languages with built-in profiling and data engineering tools.

## Python Performance Analysis

### Basic Profiling with cProfile

```bash
# Profile a Python script
python -m cProfile -s cumulative script.py

# Save profile data for analysis
python -m cProfile -o profile.stats script.py

# Analyze profile data
python -c "import pstats; p = pstats.Stats('profile.stats'); p.sort_stats('cumulative').print_stats(20)"
```

### Memory Profiling

```python
# memory_profiler - Install: pip install memory-profiler
# Add @profile decorator to functions you want to profile

from memory_profiler import profile

@profile
def analyze_data():
    data = [i ** 2 for i in range(100000)]
    return sum(data)

if __name__ == "__main__":
    analyze_data()
```

Run with: `python -m memory_profiler script.py`

### Line-by-Line Profiling

```python
# line_profiler - Install: pip install line-profiler
# Add @profile decorator to functions

@profile
def process_data(items):
    result = []
    for item in items:
        result.append(item * 2)
    return result

data = range(1000000)
process_data(data)
```

Run with: `kernprof -l -v script.py`

### Performance Timing

```python
import time
import timeit

# Simple timing
start = time.perf_counter()
# ... your code ...
end = time.perf_counter()
print(f"Execution time: {end - start:.4f} seconds")

# Precise benchmarking
execution_time = timeit.timeit(
    'sum(range(1000))',
    number=10000
)
print(f"Average time: {execution_time/10000:.6f} seconds")
```

## JavaScript/Node.js Performance

### Built-in Performance API

```javascript
// Node.js performance timing
const { performance } = require('perf_hooks');

const start = performance.now();
// ... your code ...
const end = performance.now();
console.log(`Execution time: ${end - start}ms`);

// Memory usage
console.log(process.memoryUsage());
```

### V8 Profiler

```bash
# CPU profiling
node --prof app.js

# Process the profile
node --prof-process isolate-*.log > processed.txt

# Heap snapshot
node --inspect app.js
# Then use Chrome DevTools to capture heap snapshots
```

### Benchmark.js

```javascript
// Install: npm install benchmark
const Benchmark = require('benchmark');
const suite = new Benchmark.Suite();

suite
  .add('Array#forEach', function() {
    [1,2,3,4,5].forEach(x => x * 2);
  })
  .add('for loop', function() {
    const arr = [1,2,3,4,5];
    for (let i = 0; i < arr.length; i++) {
      arr[i] * 2;
    }
  })
  .on('cycle', event => console.log(String(event.target)))
  .on('complete', function() {
    console.log('Fastest is ' + this.filter('fastest').map('name'));
  })
  .run();
```

## Java Performance Analysis

### JVM Profiling

```bash
# CPU profiling with Flight Recorder
java -XX:+FlightRecorder -XX:StartFlightRecording=duration=60s,filename=recording.jfr MyApp

# Heap dump on OutOfMemoryError
java -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/tmp/heapdump.hprof MyApp

# GC logging
java -Xlog:gc*:file=gc.log:time,uptime:filecount=5,filesize=100M MyApp
```

### JMH (Java Microbenchmark Harness)

```java
// Add dependency: org.openjdk.jmh:jmh-core
import org.openjdk.jmh.annotations.*;

@State(Scope.Thread)
public class MyBenchmark {
    
    @Benchmark
    public int testMethod() {
        int sum = 0;
        for (int i = 0; i < 1000; i++) {
            sum += i;
        }
        return sum;
    }
}
```

## Go Performance Analysis

### Built-in Profiling

```go
// CPU profiling
import (
    "os"
    "runtime/pprof"
)

func main() {
    f, _ := os.Create("cpu.prof")
    pprof.StartCPUProfile(f)
    defer pprof.StopCPUProfile()
    
    // Your code here
}
```

```bash
# Run profiling
go run main.go

# Analyze profile
go tool pprof cpu.prof
```

### Benchmarking

```go
// In *_test.go file
func BenchmarkFunction(b *testing.B) {
    for i := 0; i < b.N; i++ {
        // Code to benchmark
        sum := 0
        for j := 0; j < 1000; j++ {
            sum += j
        }
    }
}
```

Run with: `go test -bench=. -benchmem`

## Data Engineering for Performance Analysis

### Collecting Performance Metrics

```python
import time
import psutil
import json
from datetime import datetime

def collect_metrics(func):
    """Decorator to collect performance metrics"""
    def wrapper(*args, **kwargs):
        # Start metrics
        start_time = time.perf_counter()
        process = psutil.Process()
        start_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Execute function
        result = func(*args, **kwargs)
        
        # End metrics
        end_time = time.perf_counter()
        end_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        metrics = {
            "function": func.__name__,
            "timestamp": datetime.now().isoformat(),
            "execution_time_seconds": round(end_time - start_time, 4),
            "memory_used_mb": round(end_memory - start_memory, 2),
            "cpu_percent": process.cpu_percent()
        }
        
        # Save metrics
        with open("performance_metrics.jsonl", "a") as f:
            f.write(json.dumps(metrics) + "\n")
        
        return result
    return wrapper

@collect_metrics
def process_large_dataset():
    data = [i ** 2 for i in range(1000000)]
    return sum(data)
```

### Analyze Performance Data

```python
import pandas as pd
import matplotlib.pyplot as plt

# Load metrics
df = pd.read_json("performance_metrics.jsonl", lines=True)

# Basic statistics
print(df.describe())

# Find slowest functions
print("\nTop 10 slowest functions:")
print(df.nlargest(10, 'execution_time_seconds')[['function', 'execution_time_seconds']])

# Memory hogs
print("\nTop 10 memory-intensive functions:")
print(df.nlargest(10, 'memory_used_mb')[['function', 'memory_used_mb']])

# Visualize trends
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.set_index('timestamp').groupby('function')['execution_time_seconds'].plot(
    legend=True,
    title='Execution Time Over Time'
)
plt.ylabel('Execution Time (s)')
plt.savefig('performance_trend.png')
```

### Quick Performance Comparison

```bash
# Shell-based timing for quick comparisons
time python script1.py
time python script2.py

# Multiple runs with statistics
for i in {1..10}; do
  /usr/bin/time -f "%e seconds, %M KB" python script.py 2>&1 | grep seconds
done | awk '{sum+=$1; if($1>max) max=$1; if(min=="" || $1<min) min=$1} END {print "Avg:", sum/NR, "Min:", min, "Max:", max}'
```

## Optimization Recommendations

### Common Performance Patterns

```python
# BAD: String concatenation in loop
result = ""
for i in range(10000):
    result += str(i)

# GOOD: Use join
result = "".join(str(i) for i in range(10000))

# BAD: Repeated attribute lookup
for i in range(len(items)):
    process(items[i])

# GOOD: Cache attribute
items_len = len(items)
for i in range(items_len):
    process(items[i])

# BETTER: Use enumerate
for i, item in enumerate(items):
    process(item)
```

### Algorithm Complexity Analysis

```bash
# Create a script to test different input sizes
cat > benchmark_complexity.py << 'EOF'
import time
import matplotlib.pyplot as plt

def measure_time(func, input_size):
    data = list(range(input_size))
    start = time.perf_counter()
    func(data)
    return time.perf_counter() - start

# Test functions
def linear_search(arr):
    target = arr[-1]
    for item in arr:
        if item == target:
            return item

def binary_search(arr):
    target = arr[-1]
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return arr[mid]
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1

# Benchmark
sizes = [100, 500, 1000, 5000, 10000, 50000]
linear_times = [measure_time(linear_search, n) for n in sizes]
binary_times = [measure_time(binary_search, n) for n in sizes]

print(f"Input Size | Linear | Binary")
for i, size in enumerate(sizes):
    print(f"{size:10d} | {linear_times[i]:.6f}s | {binary_times[i]:.6f}s")
EOF

python benchmark_complexity.py
```

## Performance Testing Tools

### Load Testing (Web Applications)

```bash
# Apache Bench
ab -n 1000 -c 10 http://localhost:8000/

# wrk (more advanced)
wrk -t12 -c400 -d30s http://localhost:8000/

# Artillery (Node.js)
npm install -g artillery
artillery quick --count 10 --num 20 http://localhost:8000/
```

### Database Query Performance

```sql
-- PostgreSQL: Explain query plan
EXPLAIN ANALYZE SELECT * FROM users WHERE age > 25;

-- Find slow queries
SELECT query, calls, total_time, mean_time 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;
```

## Tips and Best Practices

1. **Profile Before Optimizing**: Always measure first to identify real bottlenecks
2. **Test with Realistic Data**: Use production-like data sizes and patterns
3. **Automate Metrics**: Integrate performance monitoring into CI/CD
4. **Compare Baselines**: Track performance over time to detect regressions
5. **Consider Trade-offs**: Balance performance vs. code readability and maintainability
6. **Use Appropriate Tools**: Different tools for different languages and scenarios
7. **Watch Memory**: Memory usage is as important as execution time
8. **Cache Wisely**: Implement caching for expensive operations
