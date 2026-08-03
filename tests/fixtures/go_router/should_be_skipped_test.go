package original

import "testing"

func TestCompute(t *testing.T) {
	if Compute(2) != 4 {
		t.Fatal("bad")
	}
}

func Bag() {}
