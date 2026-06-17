use std::cmp;

fn main(){
  loop {
    let nmhk: Vec<usize> = read_vec();
    let n = nmhk[0];
    let m = nmhk[1];
    let h = nmhk[2];
    let k = nmhk[3];

    if n == 0 && m == 0 && h == 0 && k == 0 { break; }

    let mut sv: Vec<u32> = Vec::new();

    for _ in 0 .. n {
      sv.push(read());
    }

    let mut vb: Vec<Vec<usize>> = vec![Vec::new();h];
    
    for _ in 0 .. m {
      let ab: Vec<usize> = read_vec();
      let a = ab[0];
      let b = ab[1];
      
      vb[b].push(a);
    }

    let mut akd: Vec<Vec<usize>> = vec![Vec::new(); h];
    akd[0] = (0 .. n).collect();
    
    for i in 1 .. h {
      for j in 0 .. n {
        let t = akd[i-1][j];
        akd[i].push(t);
      }

      for &j in &vb[i] {
        let t = akd[i][j];
        akd[i][j] = akd[i][j-1];
        akd[i][j-1] = t;
      }
    }

    let mut aku: Vec<Vec<usize>> = vec![Vec::new(); h];
    aku[h-1] = (0 .. n).collect();
    
    for i in (0 .. h-1).rev() {
      for j in 0 .. n {
        let t = aku[i+1][j];
        aku[i].push(t);
      }

      for &j in &vb[i+1] {
        let t = aku[i][j];
        aku[i][j] = aku[i][j-1];
        aku[i][j-1] = t;
      }
    }
    
    let mut ans: u32 = 0;

    for i in 0 .. k {
      ans += sv[aku[0][i]];
    }

    for i in 1 .. h {
      for &j in &vb[i] {
        let mut t: u32 = 0;
        
        for l in 0 .. n {
          if l == j - 1 || l == j {
            if akd[i-1][l] < k {
              t += sv[aku[i][l]];
            }
          } else {
            if akd[i][l] < k {
              t += sv[aku[i][l]];
            }
          }
        }

        ans = cmp::min(ans, t);
      }
    }
    
    println!("{}", ans);
  }
}

fn read<T>() -> T
  where T: std::str::FromStr,
        T::Err: std::fmt::Debug
{
  let mut buf = String::new();
  std::io::stdin().read_line(&mut buf).expect("failed to read");
  buf.trim().parse().unwrap()
}

fn read_vec<T>() -> Vec<T>
  where T: std::str::FromStr,
        T::Err: std::fmt::Debug
{
  let mut buf = String::new();
  std::io::stdin().read_line(&mut buf).expect("failed to read");
  buf.split_whitespace().map(|e| e.parse().unwrap()).collect()
}

