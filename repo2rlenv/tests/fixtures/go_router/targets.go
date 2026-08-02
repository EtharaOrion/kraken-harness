package original

func Compute(x int) int {
	return x * 2
}

type Bag struct {
	Items []int
}

func (b *Bag) Add(v int) {
	b.Items = append(b.Items, v)
}
