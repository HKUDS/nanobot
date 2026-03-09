package complete

type Merger[T any] interface {
	Merge(T) T
}

type Completer[T any] interface {
	Complete() T
}

func MergeMap[K comparable, V any](m ...map[K]V) (result map[K]V) {
	if len(m) == 0 {
		return nil
	}
	result = make(map[K]V)
	for _, mm := range m {
		for k, v := range mm {
			result[k] = v
		}
	}
	if len(result) == 0 {
		return nil
	}
	return
}

func First[T comparable](o ...T) (result T) {
	for _, v := range o {
		if v != result {
			return v
		}
	}
	return
}

func Last[T comparable](o ...T) (result T) {
	for i := len(o) - 1; i >= 0; i-- {
		if o[i] != result {
			return o[i]
		}
	}
	return
}

func Merge[T Merger[T]](opts ...T) T {
	var all T
	for _, opt := range opts {
		all = all.Merge(opt)
	}
	return all
}

func Complete[T Merger[T]](opts ...T) T {
	merged := Merge(opts...)
	if c, ok := any(merged).(Completer[T]); ok {
		return c.Complete()
	}
	return merged
}
