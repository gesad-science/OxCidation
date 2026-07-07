//https://qiita.com/tanakh/items/0ba42c7ca36cd29d0ac8 より
macro_rules! input {
    (source = $s:expr, $($r:tt)*) => {
        let mut iter = $s.split_whitespace();
        input_inner!{iter, $($r)*}
    };
    ($($r:tt)*) => {
        let s = {
            use std::io::Read;
            let mut s = String::new();
            std::io::stdin().read_to_string(&mut s).unwrap();
            s
        };
        let mut iter = s.split_whitespace();
        input_inner!{iter, $($r)*}
    };
}

macro_rules! input_inner {
    ($iter:expr) => {};
    ($iter:expr, ) => {};
    ($iter:expr, $var:ident : $t:tt $($r:tt)*) => {
        let $var = read_value!($iter, $t);
        input_inner!{$iter $($r)*}
    };
}

macro_rules! read_value {
    ($iter:expr, ( $($t:tt),* )) => {
        ( $(read_value!($iter, $t)),* )
    };
    ($iter:expr, [ $t:tt ; $len:expr ]) => {
        (0..$len).map(|_| read_value!($iter, $t)).collect::<Vec<_>>()
    };
    ($iter:expr, chars) => {
        read_value!($iter, String).chars().collect::<Vec<char>>()
    };
    ($iter:expr, usize1) => {
        read_value!($iter, usize) - 1
    };
    ($iter:expr, $t:ty) => {
        $iter.next().unwrap().parse::<$t>().expect("Parse error")
    };
}

//

fn run() {
    input! {
        n: usize,
        m: usize,
        x: [usize; n],
    }
    let len = 100_000 + 1;
    let mut cnt = vec![0; len];
    for x in x {
        cnt[x] += 1;
    }
    let mut rem = vec![0; m];
    let mut pair = vec![0; m];
    let mut ans = 0;
    for i in 0..len {
        let p = cnt[i] / 2;
        ans += p;
        pair[i % m] += p;
        rem[i % m] += cnt[i] % 2;
    }
    ans += rem[0] / 2;
    if m % 2 == 0 {
        ans += rem[m / 2] / 2;
    }
    for i in 1..m {
        if i >= m - i {
            break;
        }
        let v = std::cmp::min(rem[i], rem[m - i]);
        ans += v;
        rem[i] -= v;
        rem[m - i] -= v;
        for &(x, y) in &[(i, m - i), (m - i, i)] {
            while rem[x] >= 2 && pair[y] >= 1 {
                ans += 1;
                rem[x] -= 2;
                pair[y] -= 1;
            }
        }
    }
    println!("{}", ans);
}

fn main() {
    run();
}
